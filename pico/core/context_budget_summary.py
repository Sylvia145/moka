"""Pico 运行时实现模块。"""

from .context_budget_fields import compact_fields

CONTEXT_BUDGET_SCHEMA = "pico.context_budget_summary.v1"


def context_budget_summary(metadata):
    """执行 `context_budget_summary` 的内部逻辑。"""
    usage = dict(metadata.get("context_usage", {}) or {})
    orchestrator = dict(metadata.get("context_orchestrator", {}) or {})
    history = dict(metadata.get("history", {}) or {})
    window = int(usage.get("context_window", 0) or 0)
    reserved = int(usage.get("reserved_output_tokens", 0) or 0)
    effective_window = max(0, window - reserved)
    estimated_tokens = int(usage.get("total_estimated_tokens", 0) or 0)
    reductions = [
        *[_section_reduction(item) for item in metadata.get("budget_reductions", []) or []],
        *_microcompact_reductions(metadata),
    ]
    compact_call_usage = _compact_call_usage(orchestrator)
    return {
        "schema_version": CONTEXT_BUDGET_SCHEMA,
        "budget_unit": "tokens_estimated",
        "token_estimator": "context_usage_analyzer",
        "estimated_tokens": estimated_tokens,
        "effective_window": effective_window,
        "reserved_output_tokens": reserved,
        "pressure_ratio": round(estimated_tokens / effective_window, 4)
        if effective_window
        else 0,
        "reductions": reductions,
        "snip_count": sum(1 for item in reductions if item.get("source") == "section_reduction"),
        "prune_count": sum(1 for item in reductions if item.get("source") == "microcompact"),
        "saved_chars": _saved_chars(metadata, history, orchestrator),
        "prompt_changed_by_phase_3": False,
        **compact_fields(orchestrator, usage, compact_call_usage, _compact_net_benefit(orchestrator, compact_call_usage)),
    }


def update_from_orchestrator(summary, event):
    """执行 `update_from_orchestrator` 的内部逻辑。"""
    summary = dict(summary or {})
    orchestrator = dict(event.get("context_orchestrator", {}) or {})
    usage = dict(event.get("context_usage", {}) or {})
    compact_call_usage = _compact_call_usage(orchestrator)
    summary.update(compact_fields(orchestrator, usage, compact_call_usage, _compact_net_benefit(orchestrator, compact_call_usage)))
    return summary


def _compact_call_usage(orchestrator):
    """执行 `_compact_call_usage` 的内部逻辑。"""
    usage = orchestrator.get("compact_call_usage")
    return dict(usage) if isinstance(usage, dict) else None


def _compact_net_benefit(orchestrator, compact_call_usage):
    """执行 `_compact_net_benefit` 的内部逻辑。"""
    if not compact_call_usage:
        return None
    pre_tokens = int(orchestrator.get("pre_compact_estimated_tokens", 0) or 0)
    post_tokens = int(orchestrator.get("post_compact_estimated_tokens", 0) or 0)
    compact_tokens = int(compact_call_usage.get("total_tokens", 0) or 0)
    return pre_tokens - post_tokens - compact_tokens


def _saved_chars(metadata, history, orchestrator):
    """执行 `_saved_chars` 的内部逻辑。"""
    section_saved = sum(
        _section_reduction(item)["saved_chars"]
        for item in metadata.get("budget_reductions", []) or []
    )
    return (
        section_saved
        + int(history.get("microcompact_saved_chars", 0) or 0)
        + int(orchestrator.get("replacement_saved_chars", 0) or 0)
    )


def _section_reduction(item):
    """执行 `_section_reduction` 的内部逻辑。"""
    before = int(item.get("before_chars", 0) or 0)
    after = int(item.get("after_chars", 0) or 0)
    return {
        "source": "section_reduction",
        "section": str(item.get("section", "")),
        "saved_chars": max(0, before - after),
    }


def _microcompact_reductions(metadata):
    """执行 `_microcompact_reductions` 的内部逻辑。"""
    history = dict(metadata.get("history", {}) or {})
    saved = int(history.get("microcompact_saved_chars", 0) or 0)
    refs = list(history.get("microcompact_artifact_refs", []) or [])
    if not saved and not refs:
        return []
    return [
        {
            "source": "microcompact",
            "section": "history",
            "saved_chars": saved,
            "artifact_refs": refs,
        }
    ]
