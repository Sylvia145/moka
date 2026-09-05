"""Pico 运行时实现模块。

These helpers execute tool payloads and handle retry summaries while Engine
keeps the turn loop shape visible. Terminal-state policy lives in
completion_governance.
"""

import time

from ..providers.base import complete_model
from ..providers.errors import ProviderError
from ..tools.native import build_tool_definitions
from .completion_governance import finish_stopped_run
from .turn_transitions import (
    CONTINUE_NATIVE_TOOLS_UNAVAILABLE,
    emit_continue_transition,
)
from .workspace import clip, now


def execute_tool_payload(engine, task_state, user_message, payload):
    """执行 `execute_tool_payload` 的内部逻辑。"""
    agent = engine.runtime
    name = payload.get("name", "")
    args = payload.get("args", {})
    task_state.record_tool(name)
    tool_started_at = time.monotonic()
    agent.session_event_bus.emit(
        "tool_started", {"run_id": task_state.run_id, "tool_name": name, "args": args}
    )
    yield {"type": "tool_call", "run_id": task_state.run_id, "name": name, "args": args}

    tool_result = agent.run_tool(name, args)
    tool_metadata = dict(agent._last_tool_result_metadata or {})
    tool_duration_ms = int((time.monotonic() - tool_started_at) * 1000)
    agent.session_event_bus.emit(
        "tool_finished",
        {
            "run_id": task_state.run_id,
            "tool_name": name,
            "status": tool_metadata.get("tool_status", ""),
            "tool_error_code": tool_metadata.get("tool_error_code", ""),
            "workspace_changed": bool(tool_metadata.get("workspace_changed", False)),
            "affected_paths": list(tool_metadata.get("affected_paths", [])),
            "duration_ms": tool_duration_ms,
        },
    )
    history_item = {
        "role": "tool",
        "name": name,
        "args": args,
        "content": tool_result,
        "created_at": now(),
        "tool_status": str(tool_metadata.get("tool_status", "")),
        "tool_error_code": str(tool_metadata.get("tool_error_code", "")),
        "workspace_changed": bool(tool_metadata.get("workspace_changed", False)),
        "affected_paths": list(tool_metadata.get("affected_paths", []) or []),
    }
    if tool_metadata.get("full_output_artifact"):
        history_item.update(
            {
                "artifact_ref": tool_metadata["full_output_artifact"],
                "original_chars": int(tool_metadata.get("original_chars", 0) or 0),
                "content_sha256": str(tool_metadata.get("content_sha256", "")),
            }
        )
    if tool_metadata.get("media_refs"):
        history_item["media_refs"] = list(tool_metadata.get("media_refs", []) or [])
    agent.record(history_item)
    for notification in engine.drain_worker_notifications():
        yield {
            "type": "worker_notification",
            "run_id": getattr(agent, "current_run_id", ""),
            "content": notification,
        }
    agent.run_store.write_task_state(task_state)
    agent.emit_trace(
        task_state,
        "tool_executed",
        {
            "name": name,
            "args": args,
            "result": clip(tool_result, 500),
            "duration_ms": tool_duration_ms,
            **tool_metadata,
        },
    )
    checkpoint = agent.create_checkpoint(
        task_state, user_message, trigger="tool_executed"
    )
    agent.run_store.write_task_state(task_state)
    agent.emit_trace(
        task_state,
        "checkpoint_created",
        {"checkpoint_id": checkpoint["checkpoint_id"], "trigger": "tool_executed"},
    )
    yield {
        "type": "tool_result",
        "run_id": task_state.run_id,
        "name": name,
        "content": tool_result,
        "metadata": tool_metadata,
    }


def should_retry_model_error(exc, provider_retries):
    """执行 `should_retry_model_error` 的内部逻辑。"""
    if not isinstance(exc, ProviderError):
        return False
    code = str(getattr(exc, "code", "") or "")
    if code not in {"empty_response"}:
        return False
    return provider_retries.get(code, 0) < 1


def is_tools_unsupported_error(exc):
    """判断一次模型请求错误是否意味着“后端不接受原生 tools 参数”。

    命中此判断时 engine 不应重试同一请求（继续带 tools 还是会失败），而应关闭
    原生 function-calling、用文本协议重发本 attempt。判断保持保守：只把“明确的
    客户端参数拒绝（4xx 或 invalid_request 之类）且报错文案提及 tools/functions”
    当作降级信号，避免误吞 5xx、限流、超时等瞬时错误。
    """
    if not isinstance(exc, ProviderError):
        return False
    if getattr(exc, "retryable", False):
        return False
    http_status = getattr(exc, "http_status", None)
    if http_status is not None and int(http_status) in (408, 429):
        return False
    code = str(getattr(exc, "code", "") or "").lower()
    combined = f"{exc} {getattr(exc, 'body_excerpt', '')}".lower()
    mentions_tooling = "tool" in combined or "function" in combined
    if not mentions_tooling:
        return False
    client_error = (
        http_status is not None and 400 <= int(http_status) < 500
    ) or code in {
        "invalid_request_error",
        "bad_request",
        "unsupported_parameter",
        "unknown_parameter",
        "parameter_error",
        "validation_error",
    }
    return bool(client_error)


_STEP_LIMIT_SUMMARY_NOTICE = (
    "You have hit the per-turn tool budget (max_steps). Do not call any more tools. "
    "Right now, return a single <final>...</final> answer in the user's language that "
    "briefly covers: (1) what you accomplished this turn, (2) what remains undone, "
    "(3) how the user can continue (e.g., `/resume` then `继续`). Keep it concise."
)


def request_step_limit_summary(engine, task_state, user_message):
    """Ask the model to write a graceful step-limit summary.

    Returns the final text, or None if the model fails or refuses to comply.
    Side effects: emits a trace event but does NOT mutate session history —
    the caller decides whether to record the resulting final.
    """
    agent = engine.runtime
    started_at = time.monotonic()
    try:
        prompt, _ = agent._build_prompt_and_metadata(_STEP_LIMIT_SUMMARY_NOTICE)
        result = complete_model(
            agent.model_client, prompt, agent.max_new_tokens
        )
    except Exception as exc:
        agent.emit_trace(
            task_state,
            "step_limit_summary_failed",
            {"error": clip(str(exc), 200)},
        )
        return None
    raw = (result.text or "").strip() if result else ""
    kind, payload = parse_model_output(
        agent, agent.native_tools_enabled(), raw, getattr(result, "tool_calls", None)
    )
    duration_ms = int((time.monotonic() - started_at) * 1000)
    agent.emit_trace(
        task_state,
        "step_limit_summary",
        {"kind": kind, "duration_ms": duration_ms, "produced": bool(kind == "final")},
    )
    if kind == "final" and payload:
        return str(payload).strip()
    return None


def native_request(agent):
    """组装本次请求的双轨决策：返回 `(native_mode, tools_defs)`。

    native_mode 为 True 表示按原生 function calling 请求（带 tools 声明、解码
    结构化 tool_calls）；tools_defs 为 None 表示本次不传 tools——已降级/文本轨，
    或原生轨下没有可见工具（空 tools 数组会被部分后端拒收）。
    """
    if not agent.native_tools_enabled():
        return False, None
    return True, build_tool_definitions(agent) or None


def parse_model_output(agent, native_mode, raw, tool_calls):
    """按轨解码一次模型返回：原生轨走 `parse_native`，文本轨走 `parse`。

    原生轨允许模型用无标签纯文本直接作为最终回答（不需 `<final>`），并在模型仍吐
    `<tool>/<final>` 标签时自动回退文本解析；文本轨则要求 `<final>` 包裹或 `<tool>`
    动作。二者返回统一的 `(kind, payload)`。
    """
    if native_mode:
        return agent.parse_native(raw, tool_calls)
    return agent.parse(raw)


def handle_native_tools_unavailable(agent, task_state, exc, model_started_at):
    """后端拒绝原生 `tools` 参数时降级文本轨并落证据；返回是否已处理。

    命中即表示继续带 tools 重发本 attempt 只会再次失败，因此不重试同一请求，而是
    disable_native_tools() 让下一次 prefix 重建为 `<tool>/<final>` 文本指令。判断用
    is_tools_unsupported_error 保持保守，避免误吞 5xx/限流/超时等瞬时错误。
    """
    if not is_tools_unsupported_error(exc):
        return False
    agent.disable_native_tools()
    agent.emit_trace(
        task_state,
        "native_tools_disabled",
        {
            "code": getattr(exc, "code", ""),
            "http_status": getattr(exc, "http_status", None),
            "duration_ms": int((time.monotonic() - model_started_at) * 1000),
        },
    )
    emit_continue_transition(agent, task_state, CONTINUE_NATIVE_TOOLS_UNAVAILABLE)
    return True


def finish_aborted(engine, task_state, user_message, run_started_at):
    """Because an abort was requested, terminate the current turn as "aborted"."""
    yield from finish_stopped_run(
        engine,
        task_state,
        user_message,
        "Stopped after abort request.",
        "aborted",
        run_started_at,
    )
