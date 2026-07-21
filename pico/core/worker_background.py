"""Pico 运行时实现模块。"""

import subprocess
import threading
import time

from .workspace import now

ACTIVE_STATUSES = {"starting", "running", "stopping"}


def admit_background_task(manager, task, prompt, action):
    """原子地决定启动、入队或拒绝，避免并发 submit 绕过 pending 上限。"""
    with manager._lock:
        item = manager._get_item(task.id)
        item["admission"] = {
            "action": action,
            "admitted_at": now(),
            "max_workers": manager.max_concurrent_workers,
            "max_pending": manager.max_pending_workers,
        }
        if _active_count(manager) < manager.max_concurrent_workers:
            item["status"] = "starting"
            item["updated_at"] = now()
            item["admission"]["outcome"] = "started"
            manager.record_metric("accepted")
            outcome = "started"
        elif _pending_count(manager) < manager.max_pending_workers:
            item["status"] = "queued"
            item["updated_at"] = now()
            item["admission"].update({"outcome": "queued", "queued_monotonic": time.monotonic()})
            task.state = {"prompt": str(prompt or ""), "action": action}
            manager.record_metric("accepted")
            manager.record_metric("queued")
            outcome = "queued"
        else:
            item["status"] = "rejected"
            item["updated_at"] = now()
            item["admission"]["outcome"] = "rejected"
            manager.record_metric("rejected")
            outcome = "rejected"
    manager.runtime.session_event_bus.emit(
        "worker_submitted",
        {"worker_id": task.id, "description": task.description, "outcome": outcome},
    )
    if outcome == "queued":
        manager.runtime.session_event_bus.emit(
            "worker_queued", {"worker_id": task.id, "description": task.description}
        )
    elif outcome == "rejected":
        manager.runtime.session_event_bus.emit(
            "worker_rejected",
            {
                "worker_id": task.id,
                "code": "worker_queue_full",
                "running": manager.metrics()["running"],
                "pending": manager.metrics()["pending"],
                "max_workers": manager.max_concurrent_workers,
                "max_pending": manager.max_pending_workers,
            },
        )
    manager._save()
    if outcome == "started":
        _start_background(manager, task, prompt, action)
    return outcome


def create_worktree(manager, worker_id, subagent_type, scope):
    """执行 `create_worktree` 的内部逻辑。"""
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
    """执行 `can_run_background` 的内部逻辑。"""
    return getattr(manager.runtime, "model_client_factory", None) is not None


def start_if_capacity(manager, task, prompt, action):
    """执行 `start_if_capacity` 的内部逻辑。"""
    with manager._lock:
        if _active_count(manager) >= manager.max_concurrent_workers:
            return False
        item = manager._get_item(task.id)
        item["status"] = "starting"
        item["updated_at"] = now()
    _start_background(manager, task, prompt, action)
    return True


def queue_task(manager, task, prompt, action):
    """执行 `queue_task` 的内部逻辑。"""
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
    """执行 `start_next_queued` 的内部逻辑。"""
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
        queued_at = manager._get_item(next_task.id).get("admission", {}).get("queued_monotonic")
        next_task.state.clear()
        item = manager._get_item(next_task.id)
        item["status"] = "starting"
        item["updated_at"] = now()
        item.setdefault("admission", {})["started_at"] = now()
        manager.record_queue_wait(queued_at)
    _start_background(manager, next_task, prompt, action)


def request_stop(task):
    """执行 `request_stop` 的内部逻辑。"""
    task.stop_requested = True
    abort = getattr(task.runtime, "abort_current_turn", None)
    if callable(abort):
        abort()


def shutdown_workers(manager, timeout):
    """执行 `shutdown_workers` 的内部逻辑。"""
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
    """执行 `_active_count` 的内部逻辑。"""
    return sum(1 for item in manager.state.get("items", []) if item.get("status") in ACTIVE_STATUSES)


def _pending_count(manager):
    return sum(1 for item in manager.state.get("items", []) if item.get("status") == "queued")


def _start_background(manager, task, prompt, action):
    """执行 `_start_background` 的内部逻辑。"""
    from .worker_execution import run_worker

    task.thread = threading.Thread(
        target=run_worker, args=(manager, task, prompt, action), daemon=True, name=f"pico-worker-{task.id}"
    )
    task.thread.start()
    threading.Thread(target=_watch_timeout, args=(manager, task), daemon=True).start()


def _watch_timeout(manager, task):
    """执行 `_watch_timeout` 的内部逻辑。"""
    if not threading.Event().wait(task.timeout_seconds):
        item = manager._find_item(task.id)
        if item is None:
            # worker 已被清理（例如 clear_session / resume 重建会话，旧的 workers
            # 条目被丢弃）。超时监视线程不再持有有效条目，直接退出，避免对
            # 新会话抛 `unknown worker`。
            return
        if item.get("status") == "running":
            request_stop(task)
            if manager.transition_terminal(
                task.id, "timed_out", reason="execution_timeout", actor="timeout_watcher"
            ) is not None:
                manager.runtime.session_event_bus.emit("worker_timed_out", {"worker_id": task.id})
                manager._save()
                start_next_queued(manager)
