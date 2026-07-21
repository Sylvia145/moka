"""Pico 运行时实现模块。

管理器将内存中的执行任务与持久化会话状态同步，并在有写权限的子代理运行时
启用父代理的委派审查保护，防止两个执行者同时修改同一范围。
"""

import json
import queue
import threading
from dataclasses import dataclass, field

from .worker_background import (
    admit_background_task,
    can_run_background,
    create_worktree,
    request_stop,
    shutdown_workers,
    start_next_queued,
)
from .worker_execution import run_worker
from .worker_runtime import build_child_runtime
from .workspace import now


@dataclass
class WorkerTask:
    id: str
    description: str
    subagent_type: str
    write_scope: tuple[str, ...]
    runtime: object
    thread: threading.Thread | None = None
    stop_requested: bool = False
    state: dict = field(default_factory=dict)
    timeout_seconds: int = 60


class WorkerManager:
    def __init__(self, runtime):
        """初始化对象状态。"""
        self.runtime = runtime
        self.runtime.session.setdefault("workers", {"next_id": 1, "items": []})
        self._tasks = {}
        # admission、状态迁移和指标更新可在同一个临界区嵌套调用。
        self._lock = threading.RLock()
        self._notifications = queue.Queue()
        self.max_concurrent_workers = int(getattr(runtime, "max_concurrent_workers", 2))
        self.max_pending_workers = int(getattr(runtime, "max_pending_workers", 16))
        self._ensure_metrics_shape()

    @property
    def state(self):
        """执行 `state` 的内部逻辑。"""
        return self.runtime.session.setdefault("workers", {"next_id": 1, "items": []})

    def spawn(self, description, prompt, subagent_type="worker", write_scope=None, timeout_seconds=60):
        """执行 `spawn` 的内部逻辑。"""
        subagent_type = _clean_type(subagent_type)
        if self.runtime.runtime_mode == "plan" and subagent_type != "Explore":
            raise ValueError("plan mode only allows Explore agents")
        task = self._new_task(description, subagent_type, write_scope, timeout_seconds)
        self._tasks[task.id] = task
        # 仅写入型 worker 需要锁住父代理；Explore 子代理没有写权限，保留父代理
        # 的正常工具能力可以避免无谓地阻塞调查与汇总。
        guard_parent = subagent_type == "worker" and bool(task.write_scope)
        if can_run_background(self):
            admission = admit_background_task(self, task, prompt, action="spawn")
            if admission == "started":
                if guard_parent:
                    self.runtime.activate_delegated_review_mode(task.id)
                return self._public_payload(task, status="started")
            if admission == "queued":
                if guard_parent:
                    self.runtime.activate_delegated_review_mode(task.id)
                return self._public_payload(task, status="queued")
            # 被拒绝的写任务从未被调度，父代理不能进入 delegated_review。
            return self._public_payload(task, status="rejected")
        self._mark_starting(task.id, action="spawn")
        run_worker(self, task, prompt, action="spawn")
        if guard_parent:
            self.runtime.activate_delegated_review_mode(task.id)
        return self._public_payload(task)

    def continue_task(self, task_id, message):
        """执行 `continue_task` 的内部逻辑。"""
        task = self._get_active_task(task_id)
        item = self._get_item(task_id)
        if item.get("status") in {"running", "stopping"}:
            raise ValueError(f"worker is running: {task_id}")
        if self.runtime.runtime_mode == "plan" and task.subagent_type != "Explore":
            raise ValueError("plan mode only allows Explore agents")
        if can_run_background(self):
            admission = admit_background_task(self, task, message, action="continue")
            return self._public_payload(task, status=admission)
        self._mark_starting(task.id, action="continue")
        run_worker(self, task, message, action="continue")
        return self._public_payload(task)

    def stop_task(self, task_id):
        """执行 `stop_task` 的内部逻辑。"""
        item = self._get_item(task_id)
        if item["status"] in {"starting", "running"}:
            task = self._tasks.get(str(task_id))
            if task is not None:
                request_stop(task)
            item["status"] = "stopping"
            item["updated_at"] = now()
            self.runtime.session_event_bus.emit(
                "worker_stop_requested", {"worker_id": item["id"], "status": "stopping"}
            )
            self._save()
        elif item["status"] == "queued":
            self.transition_terminal(
                task_id, "canceled", reason="external_cancel", actor="task_stop"
            )
            task = self._tasks.get(str(task_id))
            if task is not None:
                task.state.clear()
            self.runtime.session_event_bus.emit(
                "worker_canceled", {"worker_id": item["id"], "status": "canceled"}
            )
            self._save()
            start_next_queued(self)
        return {
            "task_id": item["id"],
            "status": item["status"],
            "description": item["description"],
        }

    def shutdown(self, timeout=2.0):
        """执行 `shutdown` 的内部逻辑。"""
        return shutdown_workers(self, timeout)

    def to_dict(self):
        """执行 `to_dict` 的内部逻辑。"""
        return {
            "next_id": int(self.state.get("next_id", 1)),
            "items": [dict(item) for item in self.state.get("items", [])],
            "metrics": self.metrics(),
        }

    def metrics(self):
        """返回可持久化的调度指标快照，不把瞬时队列状态混入累计计数。"""
        metrics = dict(self.state["metrics"])
        wait_samples = int(metrics.get("queue_wait_samples", 0))
        total_wait = int(metrics.get("queue_wait_ms_total", 0))
        metrics["queue_wait_ms_avg"] = total_wait / wait_samples if wait_samples else 0.0
        metrics["running"] = sum(
            1 for item in self.state.get("items", []) if item.get("status") in {"starting", "running", "stopping"}
        )
        metrics["pending"] = sum(1 for item in self.state.get("items", []) if item.get("status") == "queued")
        metrics["max_workers"] = self.max_concurrent_workers
        metrics["max_pending"] = self.max_pending_workers
        return metrics

    def record_metric(self, name, amount=1):
        with self._lock:
            metrics = self.state["metrics"]
            metrics[name] = int(metrics.get(name, 0)) + int(amount)

    def record_queue_wait(self, queued_at):
        if not queued_at:
            return
        # monotonic 值不应进入 session；排队时间在同一进程内由此字段计算。
        import time

        waited_ms = max(0, int((time.monotonic() - float(queued_at)) * 1000))
        with self._lock:
            metrics = self.state["metrics"]
            metrics["queue_wait_samples"] = int(metrics.get("queue_wait_samples", 0)) + 1
            metrics["queue_wait_ms_total"] = int(metrics.get("queue_wait_ms_total", 0)) + waited_ms
            metrics["queue_wait_ms_max"] = max(int(metrics.get("queue_wait_ms_max", 0)), waited_ms)
        return waited_ms

    def transition_terminal(self, task_id, status, *, reason, actor):
        """提交一次终态；竞争失败代表另一执行者已先完成状态迁移。"""
        terminal = {"completed", "failed", "timed_out", "stopped", "canceled", "rejected"}
        with self._lock:
            item = self._get_item(task_id)
            previous = str(item.get("status", ""))
            if previous in terminal:
                self.record_metric("duplicate_terminal_transition")
                return None
            item["status"] = status
            item["updated_at"] = now()
            item["terminal_transition"] = {
                "from": previous,
                "to": status,
                "reason": reason,
                "actor": actor,
                "at": now(),
            }
            metric_name = "canceled" if status == "stopped" else status
            self.record_metric(metric_name)
            return item

    def _mark_starting(self, task_id, *, action):
        """为同步执行和继续执行建立与后台路径相同的启动状态。"""
        with self._lock:
            item = self._get_item(task_id)
            item["status"] = "starting"
            item["updated_at"] = now()
            item["admission"] = {"action": action, "outcome": "started", "admitted_at": now()}
            self.record_metric("accepted")

    def _new_task(self, description, subagent_type, write_scope, timeout_seconds):
        """执行 `_new_task` 的内部逻辑。"""
        with self._lock:
            worker_id = f"agent_{int(self.state.get('next_id', 1))}"
            self.state["next_id"] = int(self.state.get("next_id", 1)) + 1
        scope = tuple(_clean_scope(write_scope))
        # 工作树及其基准提交一并持久化，后续交接时才能判断子代理改动相对于
        # 哪个父工作区版本产生，并支持可审查的合并流程。
        worktree_path, base_commit = create_worktree(self, worker_id, subagent_type, scope)
        child = build_child_runtime(self.runtime, subagent_type, scope, workspace_root=worktree_path or self.runtime.root)
        item = {
            "id": worker_id,
            "description": str(description or "").strip() or "Worker task",
            "subagent_type": subagent_type,
            "write_scope": list(scope),
            "status": "idle",
            "result": "",
            "tool_steps": 0,
            "attempts": 0,
            "duration_ms": 0,
            "timeout_seconds": int(timeout_seconds),
            "worktree_path": str(worktree_path.relative_to(self.runtime.root)) if worktree_path else "",
            "base_commit": base_commit,
            "notification_drained": False,
            "admission": {},
            "created_at": now(),
            "updated_at": now(),
        }
        with self._lock:
            self.state.setdefault("items", []).append(item)
            self._save()
        return WorkerTask(worker_id, item["description"], subagent_type, scope, child, timeout_seconds=int(timeout_seconds))

    def drain_notifications(self):
        """执行 `drain_notifications` 的内部逻辑。"""
        drained = []
        while True:
            try:
                task_id, notification = self._notifications.get_nowait()
            except queue.Empty:
                break
            item = self._get_item(task_id)
            with self._lock:
                if item.get("notification_drained"):
                    continue
                item["notification_drained"] = True
                item["updated_at"] = now()
            drained.append(notification)
        if drained:
            self._save()
        return drained

    def _get_active_task(self, task_id):
        """执行 `_get_active_task` 的内部逻辑。"""
        task = self._tasks.get(str(task_id))
        if task is None:
            raise ValueError(f"unknown or inactive worker: {task_id}")
        return task

    def _find_item(self, task_id):
        """执行 `_find_item` 的内部逻辑。"""
        for item in self.state.setdefault("items", []):
            if item.get("id") == str(task_id):
                return item
        return None

    def _get_item(self, task_id):
        """执行 `_get_item` 的内部逻辑。"""
        item = self._find_item(task_id)
        if item is None:
            raise ValueError(f"unknown worker: {task_id}")
        return item

    def _public_payload(self, task, status=None):
        """执行 `_public_payload` 的内部逻辑。"""
        item = self._get_item(task.id)
        payload = {
            "task_id": task.id,
            "status": status or item["status"],
            "description": task.description,
        }
        if payload["status"] == "rejected":
            payload["error"] = {
                "code": "worker_queue_full",
                "retryable": True,
                "running": self.metrics()["running"],
                "pending": self.metrics()["pending"],
                "max_workers": self.max_concurrent_workers,
                "max_pending": self.max_pending_workers,
            }
        return payload

    def _ensure_metrics_shape(self):
        workers = self.runtime.session.setdefault("workers", {"next_id": 1, "items": []})
        metrics = workers.setdefault("metrics", {})
        for key in (
            "accepted", "queued", "rejected", "completed", "failed", "timed_out", "canceled",
            "duplicate_terminal_transition", "unhandled_thread_exception", "queue_wait_samples",
            "queue_wait_ms_total", "queue_wait_ms_max",
        ):
            metrics.setdefault(key, 0)

    def _save(self):
        """执行 `_save` 的内部逻辑。"""
        self.runtime.session_path = self.runtime.session_store.save(
            self.runtime.session
        )


def _clean_type(value):
    """执行 `_clean_type` 的内部逻辑。"""
    subagent_type = str(value or "worker").strip()
    if subagent_type not in {"worker", "Explore"}:
        raise ValueError("subagent_type must be worker or Explore")
    return subagent_type


def _clean_scope(value):
    """执行 `_clean_scope` 的内部逻辑。"""
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        raise TypeError("write_scope must be a list of workspace paths")
    return [str(item).strip() for item in value if str(item).strip()]


def dumps_payload(payload):
    """执行 `dumps_payload` 的内部逻辑。"""
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)
