"""Pico 运行时实现模块。"""

import time

from .worker_artifacts import build_change_handoff, collect_worker_artifacts
from .worker_background import start_next_queued
from .workspace import clip, now


def run_worker(manager, task, prompt, action):
    """执行 `run_worker` 的内部逻辑。"""
    item = manager._get_item(task.id)
    # cancel/timeout 可能在工作线程真正拿到 CPU 前先提交终态；不得把终态回写。
    if manager.transition_worker_state(
        task.id, {"starting"}, "running", reason="worker_thread_started", actor="worker_thread"
    ) is None:
        return
    with manager._lock:
        item["notification_drained"] = False
    manager.runtime.session_event_bus.emit(
        "worker_started",
        {"worker_id": task.id, "description": task.description, "subagent_type": task.subagent_type, "action": action},
    )
    manager._save()
    started = time.monotonic()
    try:
        result = task.runtime.ask(str(prompt or ""))
        status = "timed_out" if item.get("status") == "timed_out" else ("stopped" if task.stop_requested else "completed")
    except Exception as exc:  # noqa: BLE001 - 模型或后端失败需转为子代理结果契约。
        result = f"error: worker failed: {exc}"
        status = "failed"
    task_state = getattr(task.runtime, "current_task_state", None)
    artifacts = collect_worker_artifacts(manager.runtime.root, task.runtime, task_state)
    change_handoff = build_change_handoff(
        task.runtime.root, item.get("base_commit", ""), artifacts
    )
    change_handoff["idempotency_key"] = (
        f"{task.id}:{int(item.get('execution_sequence', 0))}:handoff"
    )
    committed = manager.transition_worker_state(
        task.id, {"running", "stopping"}, status,
        reason="worker_execution_returned", actor="worker_thread"
    )
    if committed is not None:
        with manager._lock:
            committed.update(
                {
                "result": clip(result, 2000),
                "tool_steps": int(getattr(task_state, "tool_steps", 0) or 0),
                "attempts": int(getattr(task_state, "attempts", 0) or 0),
                **artifacts,
                "change_handoff": change_handoff,
                "result_contract": {
                    "summary": clip(result, 500),
                    "changed_paths": list(artifacts["changed_paths"]),
                    "verification": dict(artifacts["verification"]),
                    "run_id": artifacts["run_id"],
                    "error_codes": list(artifacts["tool_error_codes"]),
                    "change_handoff": change_handoff,
                },
                "duration_ms": int((time.monotonic() - started) * 1000),
                "updated_at": now(),
                }
            )
        manager.publish_terminal_notification(committed)
    manager._save()
    start_next_queued(manager)
