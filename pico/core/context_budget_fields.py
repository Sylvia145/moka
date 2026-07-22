"""上下文预算摘要的共享字段。"""


def compact_fields(orchestrator, usage, compact_call_usage, net_benefit):
    return {
        "pressure_tier": orchestrator.get("pressure_tier") or usage.get("pressure_tier", ""),
        "usage_source": orchestrator.get("usage_source") or usage.get("usage_source", ""),
        "provider_usage_available": usage.get("actual_input_tokens") is not None,
        "summary_called": bool(orchestrator.get("summary_called", False)),
        "summary_mode": str(orchestrator.get("summary_mode", "")),
        "summary_delta_event_count": int(orchestrator.get("summary_delta_event_count", 0) or 0),
        "compact_call_usage": compact_call_usage,
        "compact_net_benefit_tokens": net_benefit,
        "compact_summary_has_next_steps": orchestrator.get("compact_summary_has_next_steps"),
        "compact_summary_has_file_references": orchestrator.get("compact_summary_has_file_references"),
        "pre_compact_estimated_tokens": int(orchestrator.get("pre_compact_estimated_tokens", 0) or 0),
        "post_compact_estimated_tokens": int(orchestrator.get("post_compact_estimated_tokens", 0) or 0),
        "replacement_cache_hits": int(orchestrator.get("replacement_cache_hits", 0) or 0),
        "replacement_records_created": int(orchestrator.get("replacement_records_created", 0) or 0),
        "replacement_ledger_enabled": bool(orchestrator.get("replacement_ledger_enabled", False)),
        "cached_tokens": int(usage.get("cached_tokens", 0) or 0),
    }
