"""上下文压缩质量的 final-readiness 判定。"""


def compact_net_negative(context):
    try:
        return context.get("compact_net_benefit_tokens") is not None and int(context.get("compact_net_benefit_tokens")) < 0
    except (TypeError, ValueError):
        return False


def compact_summary_quality_low(context):
    return str(context.get("summary_mode", "")) == "llm" and (
        context.get("compact_summary_has_next_steps") is False or context.get("compact_summary_has_file_references") is False
    )


def context_pressure_compaction_failed(context):
    if str(context.get("pressure_tier", "")) != "tier3_summary":
        return False
    try:
        pre, post = int(context.get("pre_compact_estimated_tokens", 0) or 0), int(context.get("post_compact_estimated_tokens", 0) or 0)
    except (TypeError, ValueError):
        return False
    return pre > 0 and post >= pre
