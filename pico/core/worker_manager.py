"""Session-scoped worker lifecycle for subagents."""

import json
import queue
import threading
from dataclasses import dataclass, field

from .worker_background import (
    can_run_background,
    create_worktree,
    queue_task,
    request_stop,
    shutdown_workers,
    start_if_capacity,
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
        self.runtime = runtime
        self.runtime.session.setdefault("workers", {"next_id": 1, "items": []})
        self._tasks = {}
        self._lock = threading.Lock()
        self._notifications = queue.Queue()
        self.max_concurrent_workers = int(getattr(runtime, "max_concurrent_workers", 2))

    @property
    def state(self):
        return self.runtime.session.setdefault("workers", {"next_id": 1, "items": []})

    def spawn(self, description, prompt, subagent_type="worker", write_scope=None, timeout_seconds=60):
        subagent_type = _clean_type(subagent_type)
        if self.runtime.runtime_mode == "plan" and subagent_type != "Explore":
            raise ValueError("plan mode only allows Explore agents")
        task = self._new_task(description, subagent_type, write_scope, timeout_seconds)
        self._tasks[task.id] = task
        if can_run_background(self):
            if start_if_capacity(self, task, prompt, action="spawn"):
                return self._public_payload(task, status="started")
            queue_task(self, task, prompt, action="spawn")
            return self._public_payload(task, status="queued")
        run_worker(self, task, prompt, action="spawn")
        return self._public_payload(task)

    def continue_task(self, task_id, message):
        task = self._get_active_task(task_id)
        item = self._get_item(task_id)
        if item.get("status") in {"running", "stopping"}:
            raise ValueError(f"worker is running: {task_id}")
        if self.runtime.runtime_mode == "plan" and task.subagent_type != "Explore":
            raise ValueError("plan mode only allows Explore agents")
        if can_run_background(self):
            if start_if_capacity(self, task, message, action="continue"):
                return self._public_payload(task, status="started")
            queue_task(self, task, message, action="continue")
            return self._public_payload(task, status="queued")
        run_worker(self, task, message, action="continue")
        return self._public_payload(task)

    def stop_task(self, task_id):
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
            with self._lock:
                item["status"] = "canceled"
                item["updated_at"] = now()
            task = self._tasks.get(str(task_id))
            if task is not None:
                task.state.clear()
            self.runtime.session_event_bus.emit(
                "worker_canceled", {"worker_id": item["id"], "status": "canceled"}
            )
            self._save()
        return {
            "task_id": item["id"],
            "status": item["status"],
            "description": item["description"],
        }

    def shutdown(self, timeout=2.0):
        return shutdown_workers(self, timeout)

    def to_dict(self):
        return {
            "next_id": int(self.state.get("next_id", 1)),
            "items": [dict(item) for item in self.state.get("items", [])],
        }

    def _new_task(self, description, subagent_type, write_scope, timeout_seconds):
        with self._lock:
            worker_id = f"agent_{int(self.state.get('next_id', 1))}"
            self.state["next_id"] = int(self.state.get("next_id", 1)) + 1
        scope = tuple(_clean_scope(write_scope))
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
            "created_at": now(),
            "updated_at": now(),
        }
        with self._lock:
            self.state.setdefault("items", []).append(item)
            self._save()
        return WorkerTask(worker_id, item["description"], subagent_type, scope, child, timeout_seconds=int(timeout_seconds))

    def drain_notifications(self):
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
        task = self._tasks.get(str(task_id))
        if task is None:
            raise ValueError(f"unknown or inactive worker: {task_id}")
        return task

    def _get_item(self, task_id):
        for item in self.state.setdefault("items", []):
            if item.get("id") == str(task_id):
                return item
        raise ValueError(f"unknown worker: {task_id}")

    def _public_payload(self, task, status=None):
        item = self._get_item(task.id)
        return {
            "task_id": task.id,
            "status": status or item["status"],
            "description": task.description,
        }

    def _save(self):
        self.runtime.session_path = self.runtime.session_store.save(
            self.runtime.session
        )


def _clean_type(value):
    subagent_type = str(value or "worker").strip()
    if subagent_type not in {"worker", "Explore"}:
        raise ValueError("subagent_type must be worker or Explore")
    return subagent_type


def _clean_scope(value):
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        raise TypeError("write_scope must be a list of workspace paths")
    return [str(item).strip() for item in value if str(item).strip()]


def dumps_payload(payload):
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)
