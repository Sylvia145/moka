"""Pico 运行时实现模块。"""

import uuid
from datetime import datetime

from ..features import memory as memorylib
from .plan_mode import PlanModeController
from .session_events import SessionEventBus
from .todo_ledger import TodoLedger
from .worker_manager import WorkerManager
from .workspace import now


def resume_runtime_session(runtime, session_id):
    """执行 `resume_runtime_session` 的内部逻辑。"""
    _shutdown_workers(runtime)
    runtime.session = runtime.session_store.load(session_id)
    _rebind(runtime, emit_started=False)
    return runtime.session["id"]


def clear_runtime_session(runtime):
    """执行 `clear_runtime_session` 的内部逻辑。"""
    _shutdown_workers(runtime)
    runtime.session = {
        "id": datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6],
        "created_at": now(),
        "workspace_root": runtime.workspace.repo_root,
        "history": [],
        "memory": memorylib.default_memory_state(),
    }
    _rebind(runtime, emit_started=True)
    return runtime.session["id"]


def _rebind(runtime, emit_started):
    """执行 `_rebind` 的内部逻辑。"""
    runtime._ensure_session_shape()
    runtime.session_event_bus = SessionEventBus(
        runtime.session["id"],
        runtime.session_store.event_path(runtime.session["id"]),
        redact=runtime.redact_artifact,
    )
    if emit_started:
        runtime.session_event_bus.emit(
            "session_started", {"workspace_root": runtime.workspace.repo_root}
        )
    runtime.plan_mode = PlanModeController(runtime)
    runtime.memory = memorylib.LayeredMemory(
        runtime.session.setdefault("memory", memorylib.default_memory_state()),
        workspace_root=runtime.root,
    )
    runtime.session["memory"] = runtime.memory.to_dict()
    runtime.todo_ledger = TodoLedger(runtime)
    runtime.worker_manager = WorkerManager(runtime)
    runtime._active_tool_profile_name = (
        "plan"
        if runtime.runtime_mode == "plan"
        else "readonly"
        if runtime.read_only
        else "delegated_review"
        if runtime.delegation_guard_active
        else "default"
    )
    runtime.resume_state = runtime.evaluate_resume_state()
    runtime.session_path = runtime.session_store.save(runtime.session)
    runtime.current_turn_id = ""
    runtime.current_run_id = ""
    runtime.current_run_dir = None
    runtime.current_task_state = None
    runtime.refresh_prefix(force=True)


def _shutdown_workers(runtime):
    """执行 `_shutdown_workers` 的内部逻辑。"""
    manager = getattr(runtime, "worker_manager", None)
    shutdown = getattr(manager, "shutdown", None)
    if callable(shutdown):
        shutdown()
