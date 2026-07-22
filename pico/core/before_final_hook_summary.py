"""before-final hook 摘要的可归约指标。"""


def reduce_before_final_hook_summary(summary, event, schema_version):
    """按事件累计 hook 结果，供运行报告消费。"""
    summary = dict(summary or {})
    summary.setdefault("schema_version", schema_version)
    action = str(event.get("action", "allow"))
    summary[f"{action}_count"] = int(summary.get(f"{action}_count", 0) or 0) + 1
    for key in ("allow_count", "warn_count", "runtime_notice_count", "block_count"):
        summary.setdefault(key, 0)
    summary["last_action"] = action
    summary["last_reason"] = str(event.get("reason", ""))
    summary["last_hook"] = str(event.get("hook", ""))
    return summary
