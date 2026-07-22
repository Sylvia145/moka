"""Worker 任务对象、会话索引与外部返回载荷。"""

import json
from dataclasses import dataclass, field

from .worker_background import create_worktree
from .worker_runtime import build_child_runtime
from .workspace import now


@dataclass
class WorkerTask:
    id: str
    description: str
    subagent_type: str
    write_scope: tuple[str, ...]
    runtime: object
    thread: object = None
    stop_requested: bool = False
    state: dict = field(default_factory=dict)
    timeout_seconds: int = 60


def new_task(manager, description, subagent_type, write_scope, timeout_seconds):
    with manager._lock:
        worker_id = f"agent_{int(manager.state.get('next_id', 1))}"
        manager.state["next_id"] = int(manager.state.get("next_id", 1)) + 1
    scope = tuple(clean_scope(write_scope))
    worktree_path, base_commit = create_worktree(manager, worker_id, subagent_type, scope)
    child = build_child_runtime(
        manager.runtime, subagent_type, scope, workspace_root=worktree_path or manager.runtime.root
    )
    item = {
        "id": worker_id, "description": str(description or "").strip() or "Worker task",
        "subagent_type": subagent_type, "write_scope": list(scope), "status": "idle",
        "result": "", "tool_steps": 0, "attempts": 0, "duration_ms": 0,
        "timeout_seconds": int(timeout_seconds),
        "worktree_path": str(worktree_path.relative_to(manager.runtime.root)) if worktree_path else "",
        "base_commit": base_commit, "notification_drained": False,
        "notification_pending_keys": [], "notification_delivery_keys": [],
        "execution_sequence": 0, "admission": {}, "created_at": now(), "updated_at": now(),
    }
    with manager._lock:
        manager.state.setdefault("items", []).append(item)
        manager._save()
    return WorkerTask(worker_id, item["description"], subagent_type, scope, child, timeout_seconds=int(timeout_seconds))


def restore_queued_task(manager, item):
    """从会话 admission 快照重建尚未启动的 Worker。"""
    scope = tuple(item.get("write_scope", []))
    worktree_value = str(item.get("worktree_path", "")).strip()
    workspace_root = manager.runtime.root / worktree_value if worktree_value else manager.runtime.root
    child = build_child_runtime(
        manager.runtime, str(item.get("subagent_type", "worker")), scope, workspace_root=workspace_root
    )
    admission = dict(item.get("admission", {}))
    return WorkerTask(
        str(item["id"]), str(item.get("description", "Worker task")),
        str(item.get("subagent_type", "worker")), scope, child,
        state={"prompt": str(admission.get("prompt", "")), "action": str(admission.get("action", "spawn"))},
        timeout_seconds=int(item.get("timeout_seconds", manager.runtime.worker_timeout_seconds)),
    )


def get_item(manager, task_id):
    for item in manager.state.setdefault("items", []):
        if item.get("id") == str(task_id):
            return item
    raise ValueError(f"unknown worker: {task_id}")


def get_active_task(manager, task_id):
    task = manager._tasks.get(str(task_id))
    if task is None:
        raise ValueError(f"unknown or inactive worker: {task_id}")
    return task


def public_payload(manager, task, status=None):
    item = get_item(manager, task.id)
    payload = {"task_id": task.id, "status": status or item["status"], "description": task.description}
    if payload["status"] == "rejected":
        metrics = manager.metrics()
        payload["error"] = {
            "code": "worker_queue_full", "retryable": True,
            "running": metrics["running"], "pending": metrics["pending"],
            "max_workers": manager.max_concurrent_workers, "max_pending": manager.max_pending_workers,
        }
    return payload


def clean_type(value):
    subagent_type = str(value or "worker").strip()
    if subagent_type not in {"worker", "Explore"}:
        raise ValueError("subagent_type must be worker or Explore")
    return subagent_type


def clean_scope(value):
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        raise TypeError("write_scope must be a list of workspace paths")
    return [str(item).strip() for item in value if str(item).strip()]


def dumps_payload(payload):
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)
