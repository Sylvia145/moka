"""Background scheduling and workspace isolation for worker tasks."""

import subprocess
import threading
import time

from .workspace import now

ACTIVE_STATUSES = {"starting", "running", "stopping"}


def create_worktree(manager, worker_id, subagent_type, scope):
    if subagent_type != "worker" or not scope or not (manager.runtime.root / ".git").exists():
        return None, ""
    target = manager.runtime.root / ".worktrees" / worker_id
    target.parent.mkdir(parents=True, exist_ok=True)
    base = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=manager.runtime.root, capture_output=True, text=True, check=True
    ).stdout.strip()
    subprocess.run(
        ["git", "worktree", "add", "--detach", str(target), base],
        cwd=manager.runtime.root,
        capture_output=True,
        text=True,
        check=True,
    )
    return target, base


def can_run_background(manager):
    return getattr(manager.runtime, "model_client_factory", None) is not None


def start_if_capacity(manager, task, prompt, action):
    with manager._lock:
        if _active_count(manager) >= manager.max_concurrent_workers:
            return False
        item = manager._get_item(task.id)
        item["status"] = "starting"
        item["updated_at"] = now()
    _start_background(manager, task, prompt, action)
    return True


def queue_task(manager, task, prompt, action):
    item = manager._get_item(task.id)
    with manager._lock:
        item["status"] = "queued"
        item["updated_at"] = now()
        task.state = {"prompt": str(prompt or ""), "action": action}
    manager.runtime.session_event_bus.emit(
        "worker_queued", {"worker_id": task.id, "description": task.description}
    )
    manager._save()


def start_next_queued(manager):
    with manager._lock:
        if _active_count(manager) >= manager.max_concurrent_workers:
            return
        next_task = next(
            (task for task in manager._tasks.values() if manager._get_item(task.id).get("status") == "queued"),
            None,
        )
        if next_task is None:
            return
        prompt = next_task.state.get("prompt", "")
        action = next_task.state.get("action", "spawn")
        next_task.state.clear()
        item = manager._get_item(next_task.id)
        item["status"] = "starting"
        item["updated_at"] = now()
    _start_background(manager, next_task, prompt, action)


def request_stop(task):
    task.stop_requested = True
    abort = getattr(task.runtime, "abort_current_turn", None)
    if callable(abort):
        abort()


def shutdown_workers(manager, timeout):
    tasks = list(manager._tasks.values())
    for task in tasks:
        item = manager._get_item(task.id)
        if item.get("status") in ACTIVE_STATUSES:
            request_stop(task)
            with manager._lock:
                item["status"] = "stopping"
                item["updated_at"] = now()
            manager.runtime.session_event_bus.emit(
                "worker_stop_requested", {"worker_id": item["id"], "status": "stopping"}
            )
        elif item.get("status") == "queued":
            with manager._lock:
                item["status"] = "canceled"
                item["updated_at"] = now()
            task.state.clear()
    if tasks:
        manager._save()
    deadline = time.monotonic() + float(timeout)
    for task in tasks:
        thread = task.thread
        if thread is not None and thread.is_alive():
            remaining = max(0.0, deadline - time.monotonic())
            if remaining:
                thread.join(remaining)
    return {"stopped": sum(1 for task in tasks if task.stop_requested)}


def _active_count(manager):
    return sum(1 for item in manager.state.get("items", []) if item.get("status") in ACTIVE_STATUSES)


def _start_background(manager, task, prompt, action):
    from .worker_execution import run_worker

    task.thread = threading.Thread(
        target=run_worker, args=(manager, task, prompt, action), daemon=True, name=f"pico-worker-{task.id}"
    )
    task.thread.start()
    threading.Thread(target=_watch_timeout, args=(manager, task), daemon=True).start()


def _watch_timeout(manager, task):
    if not threading.Event().wait(task.timeout_seconds):
        item = manager._get_item(task.id)
        if item.get("status") == "running":
            request_stop(task)
            with manager._lock:
                item["status"] = "timed_out"
                item["updated_at"] = now()
            manager.runtime.session_event_bus.emit("worker_timed_out", {"worker_id": task.id})
            manager._save()
