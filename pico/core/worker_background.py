"""Pico 运行时实现模块。"""

import subprocess
import threading
import time
import weakref

from .worker_state import record_metric, record_queue_wait
from .workspace import now

ACTIVE_STATUSES = {"starting", "running", "stopping"}

_worker_managers = weakref.WeakSet()
_worker_excepthook_installed = False


def register_worker_manager(manager):
    """注册 manager 并在首次注册时安装 worker 线程异常钩子。"""
    global _worker_excepthook_installed
    _worker_managers.add(manager)
    if _worker_excepthook_installed:
        return
    original_hook = threading.excepthook

    def worker_excepthook(args):
        thread = args.thread
        thread_name = str(getattr(thread, "name", "")) if thread is not None else ""
        if not thread_name.startswith("pico-worker"):
            return
        worker_id = thread_name.removeprefix("pico-worker-")
        managers = list(_worker_managers)
        manager = next(
            (m for m in managers if worker_id in m._tasks), None
        ) or (managers[-1] if managers else None)
        if manager is not None:
            try:
                record_metric(manager, "unhandled_thread_exception")
                manager.runtime.session_event_bus.emit(
                    "worker_thread_exception",
                    {"worker_id": worker_id, "exc": str(args.exc_value)},
                )
            except Exception:  # noqa: BLE001,S110 - 审计钩子尽力而为，不阻断原始处理
                pass
        if original_hook is not None:
            original_hook(args)

    threading.excepthook = worker_excepthook
    _worker_excepthook_installed = True


def admit_background_task(manager, task, prompt, action):
    """原子地决定启动、入队或拒绝，避免并发 submit 绕过 pending 上限。"""
    with manager._lock:
        item = manager._get_item(task.id)
        item["admission"] = {
            "action": action,
            "admitted_at": now(),
            "max_workers": manager.max_concurrent_workers,
            "max_pending": manager.max_pending_workers,
            "execution_sequence": int(item.get("execution_sequence", 0)) + 1,
            "prompt": str(prompt or ""),
        }
        item["execution_sequence"] = item["admission"]["execution_sequence"]
        if _active_count(manager) < manager.max_concurrent_workers:
            manager.transition_worker_state(
                task.id, {"idle", "completed", "failed", "stopped", "canceled"}, "starting",
                reason="admission_capacity_available", actor="scheduler"
            )
            item["admission"].update({"outcome": "started", "started_at": now()})
            record_metric(manager, "accepted")
            outcome = "started"
        elif _pending_count(manager) < manager.max_pending_workers:
            manager.transition_worker_state(
                task.id, {"idle", "completed", "failed", "stopped", "canceled"}, "queued",
                reason="admission_capacity_exhausted", actor="scheduler"
            )
            item["admission"].update({"outcome": "queued", "queued_monotonic": time.monotonic()})
            task.state = {"prompt": str(prompt or ""), "action": action}
            record_metric(manager, "accepted")
            record_metric(manager, "queued")
            outcome = "queued"
        else:
            manager.transition_worker_state(
                task.id, {"idle", "completed", "failed", "stopped", "canceled"}, "rejected",
                reason="worker_queue_full", actor="scheduler"
            )
            item["admission"]["outcome"] = "rejected"
            # 被拒绝的写 Worker 从未启动，清理提前创建的 worktree，避免资源泄漏。
            remove_worktree(manager, task.id)
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


def remove_worktree(manager, worker_id):
    """清理从未启动即终态的写 Worker 提前创建的 worktree，避免资源泄漏。

    仅对 rejected 与 queued->canceled 调用：这些 Worker 从未产生可审核的变更，
    父 Agent 无需 review 其 worktree。失败时通过 session event 暴露，不影响状态机。
    """
    item = manager._find_item(worker_id)
    if item is None:
        return False
    worktree_value = str(item.get("worktree_path", "")).strip()
    if not worktree_value:
        return False
    target = manager.runtime.root / worktree_value
    try:
        subprocess.run(
            ["git", "worktree", "remove", "--force", str(target)],
            cwd=manager.runtime.root,
            capture_output=True,
            text=True,
            check=True,
        )
        manager.runtime.session_event_bus.emit(
            "worker_worktree_removed", {"worker_id": str(worker_id)}
        )
        return True
    except subprocess.CalledProcessError:
        manager.runtime.session_event_bus.emit(
            "worker_worktree_remove_failed",
            {"worker_id": str(worker_id), "path": worktree_value},
        )
        return False


def cancel_queued_worker(manager, task_id, *, reason, actor):
    """queued -> canceled 的单一入口：清状态、清理 worktree、通知并持久化。

    不负责启动下一个 queued，由调用方决定（外部取消要释放队首，会话关闭不需要）。
    """
    item = manager._get_item(task_id)
    committed = manager.transition_worker_state(
        task_id, {"queued"}, "canceled", reason=reason, actor=actor
    )
    task = manager._tasks.get(str(task_id))
    if task is not None:
        task.state.clear()
    remove_worktree(manager, task_id)
    manager.runtime.session_event_bus.emit(
        "worker_canceled", {"worker_id": str(task_id), "status": "canceled"}
    )
    if committed is not None:
        manager.publish_terminal_notification(committed)
    manager._save()
    return item


def can_run_background(manager):
    """执行 `can_run_background` 的内部逻辑。"""
    return getattr(manager.runtime, "model_client_factory", None) is not None


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
        manager.transition_worker_state(
            next_task.id, {"queued"}, "starting", reason="queue_capacity_released", actor="scheduler"
        )
        item.setdefault("admission", {})["started_at"] = now()
        record_queue_wait(manager, queued_at)
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
            committed = manager.transition_worker_state(
                task.id, ACTIVE_STATUSES, "canceled", reason="session_shutdown", actor="session_lifecycle"
            )
            if committed is not None:
                manager.publish_terminal_notification(committed)
            manager.runtime.session_event_bus.emit(
                "worker_stop_requested", {"worker_id": item["id"], "status": "stopping"}
            )
        elif item.get("status") == "queued":
            cancel_queued_worker(
                manager, task.id, reason="session_shutdown", actor="session_lifecycle"
            )
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
            if manager.transition_worker_state(
                task.id, {"running"}, "timed_out", reason="execution_timeout", actor="timeout_watcher"
            ) is not None:
                item = manager._get_item(task.id)
                manager.publish_terminal_notification(item)
                manager.runtime.session_event_bus.emit("worker_timed_out", {"worker_id": task.id})
                manager._save()
                start_next_queued(manager)
