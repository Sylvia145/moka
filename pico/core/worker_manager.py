"""Pico 运行时实现模块。

管理器将内存中的执行任务与持久化会话状态同步，并在有写权限的子代理运行时
启用父代理的委派审查保护，防止两个执行者同时修改同一范围。
"""

import queue
import threading

from .worker_background import (
    admit_background_task,
    can_run_background,
    cancel_queued_worker,
    register_worker_manager,
    request_stop,
    shutdown_workers,
    start_next_queued,
)
from .worker_execution import run_worker
from .worker_notifications import render_worker_notification
from .worker_state import (
    ensure_metrics,
    metrics_snapshot,
    record_metric,
    transition_worker_state,
)
from .worker_tasks import (
    clean_type,
    get_active_task,
    get_item,
    new_task,
    public_payload,
)
from .workspace import now


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
        ensure_metrics(self.state)
        register_worker_manager(self)

    @property
    def state(self):
        """执行 `state` 的内部逻辑。"""
        return self.runtime.session.setdefault("workers", {"next_id": 1, "items": []})

    def spawn(self, description, prompt, subagent_type="worker", write_scope=None, timeout_seconds=None):
        """执行 `spawn` 的内部逻辑。"""
        subagent_type = clean_type(subagent_type)
        if self.runtime.runtime_mode == "plan" and subagent_type != "Explore":
            raise ValueError("plan mode only allows Explore agents")
        timeout_seconds = int(timeout_seconds or self.runtime.worker_timeout_seconds)
        task = new_task(self, description, subagent_type, write_scope, timeout_seconds)
        self._tasks[task.id] = task
        # 仅写入型 worker 需要锁住父代理；Explore 子代理没有写权限，保留父代理
        # 的正常工具能力可以避免无谓地阻塞调查与汇总。
        guard_parent = subagent_type == "worker" and bool(task.write_scope)
        if can_run_background(self):
            admission = admit_background_task(self, task, prompt, action="spawn")
            if admission == "started":
                if guard_parent:
                    self.runtime.activate_delegated_review_mode(task.id)
                return public_payload(self, task, status="started")
            if admission == "queued":
                if guard_parent:
                    self.runtime.activate_delegated_review_mode(task.id)
                return public_payload(self, task, status="queued")
            # 被拒绝的写任务从未被调度，父代理不能进入 delegated_review。
            return public_payload(self, task, status="rejected")
        self._mark_starting(task.id, action="spawn")
        run_worker(self, task, prompt, action="spawn")
        if guard_parent:
            self.runtime.activate_delegated_review_mode(task.id)
        return public_payload(self, task)

    def continue_task(self, task_id, message):
        """执行 `continue_task` 的内部逻辑。"""
        task = get_active_task(self, task_id)
        item = get_item(self, task_id)
        if item.get("status") in {"running", "stopping"}:
            raise ValueError(f"worker is running: {task_id}")
        if self.runtime.runtime_mode == "plan" and task.subagent_type != "Explore":
            raise ValueError("plan mode only allows Explore agents")
        if can_run_background(self):
            admission = admit_background_task(self, task, message, action="continue")
            return public_payload(self, task, status=admission)
        self._mark_starting(task.id, action="continue")
        run_worker(self, task, message, action="continue")
        return public_payload(self, task)

    def stop_task(self, task_id):
        """执行 `stop_task` 的内部逻辑。"""
        item = get_item(self, task_id)
        if item["status"] in {"starting", "running"}:
            task = self._tasks.get(str(task_id))
            if task is not None:
                request_stop(task)
            committed = self.transition_worker_state(
                task_id, {"starting", "running"}, "canceled", reason="external_cancel", actor="task_stop"
            )
            if committed is not None:
                self.publish_terminal_notification(committed)
            self.runtime.session_event_bus.emit("worker_stop_requested", {"worker_id": item["id"], "status": "canceled"})
            self._save()
            start_next_queued(self)
        elif item["status"] == "queued":
            cancel_queued_worker(self, task_id, reason="external_cancel", actor="task_stop")
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
        return metrics_snapshot(self)

    def transition_worker_state(self, task_id, expected_states, status, *, reason, actor):
        return transition_worker_state(
            self, task_id, expected_states, status, reason=reason, actor=actor
        )

    def _mark_starting(self, task_id, *, action):
        """为同步执行和继续执行建立与后台路径相同的启动状态。"""
        with self._lock:
            item = self.transition_worker_state(
                task_id, {"idle", "completed", "failed", "stopped", "canceled"}, "starting",
                reason="synchronous_admission", actor="scheduler"
            )
            if item is None:
                raise ValueError(f"worker cannot start from its current state: {task_id}")
            item["admission"] = {"action": action, "outcome": "started", "admitted_at": now(), "started_at": now()}
            item["execution_sequence"] = int(item.get("execution_sequence", 0)) + 1
            item["admission"]["execution_sequence"] = item["execution_sequence"]
            record_metric(self, "accepted")

    def drain_notifications(self):
        """执行 `drain_notifications` 的内部逻辑。"""
        drained = []
        while True:
            try:
                notification_key, task_id, notification = self._notifications.get_nowait()
            except queue.Empty:
                break
            item = get_item(self, task_id)
            with self._lock:
                delivered = item.setdefault("notification_delivery_keys", [])
                if notification_key in delivered:
                    continue
                delivered.append(notification_key)
                item["notification_drained"] = True
                item["updated_at"] = now()
            drained.append(notification)
        if drained:
            self._save()
        return drained

    def publish_terminal_notification(self, item):
        """按 worker 执行轮次去重终态通知与交接引用。"""
        admission = item.get("admission", {})
        sequence = int(admission.get("execution_sequence", 0))
        key = f"{item['id']}:{sequence}:terminal"
        with self._lock:
            pending = item.setdefault("notification_pending_keys", [])
            delivered = item.setdefault("notification_delivery_keys", [])
            if key in pending or key in delivered:
                return False
            pending.append(key)
        self._notifications.put((key, item["id"], render_worker_notification(item)))
        self.runtime.session_event_bus.emit(
            "worker_finished",
            {"worker_id": item["id"], "status": item["status"], "delivery_key": key},
        )
        return True

    def _get_item(self, task_id):
        """执行 `_get_item` 的内部逻辑。"""
        return get_item(self, task_id)

    def _find_item(self, task_id):
        try:
            return get_item(self, task_id)
        except ValueError:
            return None

    def _save(self):
        """执行 `_save` 的内部逻辑。"""
        self.runtime.session_path = self.runtime.session_store.save(
            self.runtime.session
        )
