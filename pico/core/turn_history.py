"""Pico 运行时实现模块。

TurnHistoryBuilder renders persisted conversation history into a prompt-ready
transcript. It can project old large tool results as artifact-backed stubs, but
it must not rewrite the stored session history.
"""

import json
from collections import OrderedDict

from .context_replacements import ReplacementLedger
from .context_retention import ContextRetentionPolicy, RetentionContext
from .media_history import render_media_refs

HistoryRetentionContext = RetentionContext

PRESSURE_LIMITS = {
    "tier1_snip": (2, 60),
    "tier2_prune": (2, 40),
    "tier3_summary": (1, 20),
}


def tail_clip(text, limit):
    """执行 `tail_clip` 的内部逻辑。"""
    text = str(text)
    if limit <= 0:
        return ""
    if len(text) <= limit:
        return text
    if limit <= 3:
        return text[:limit]
    return text[: limit - 3] + "..."


class TurnHistoryBuilder:
    def __init__(self, agent):
        """初始化对象状态。"""
        self.agent = agent

    def enrich(self, item):
        """执行 `enrich` 的内部逻辑。"""
        item = dict(item)
        if not item.get("turn_id"):
            current_turn = str(getattr(self.agent, "current_turn_id", "") or "")
            if not current_turn:
                if item.get("role") == "user" or not self.agent.session.get("_manual_turn_id"):
                    self.agent.session["_manual_turn_seq"] = int(self.agent.session.get("_manual_turn_seq", 0)) + 1
                    self.agent.session["_manual_turn_id"] = f"manual_{self.agent.session['_manual_turn_seq']:06d}"
                current_turn = str(self.agent.session.get("_manual_turn_id", "legacy"))
            item["turn_id"] = current_turn
        if not item.get("run_id"):
            item["run_id"] = str(getattr(self.agent, "current_run_id", "") or "")
        if not item.get("event_id"):
            self.agent.session["_event_seq"] = int(self.agent.session.get("_event_seq", 0)) + 1
            item["event_id"] = f"event_{self.agent.session['_event_seq']:06d}"
        item.setdefault("source", "runtime")
        return item

    def raw_text(self, history):
        """执行 `raw_text` 的内部逻辑。"""
        if not history:
            return "Transcript:\n- empty"
        return "\n".join(["Transcript:", *self._render_turn_lines(history, line_limit=2000)])

    def render_section(self, budget, pressure=None):
        """执行 `render_section` 的内部逻辑。"""
        history = list(getattr(self.agent, "session", {}).get("history", []))
        raw = self.raw_text(history)
        if not history:
            return raw, {
                "rendered_entries": [],
                "recent_window": 0,
                "old_turn_line_limit": 80,
                "older_entries_count": 0,
                "collapsed_duplicate_reads": 0,
                "reused_file_summary_count": 0,
                "summarized_tool_count": 0,
                "rendered_turns": 0,
            }

        turns = self._group_turns(history)
        recent_window, old_turn_line_limit = self._pressure_limits(pressure)
        recent_turns = set(list(turns)[-recent_window:])
        entries, details = self._compressed_turn_entries(turns, recent_turns, old_turn_line_limit)
        rendered_entries = []
        for entry in reversed(entries):
            candidate = entry["lines"] + rendered_entries
            if len("\n".join(["Transcript:", *candidate])) <= budget:
                rendered_entries = candidate
                continue
            if entry["turn_id"] in recent_turns:
                clipped = [tail_clip(line, max(40, budget // max(1, len(entry["lines"])))) for line in entry["lines"]]
                candidate = clipped + rendered_entries
                if len("\n".join(["Transcript:", *candidate])) <= budget:
                    rendered_entries = candidate
        rendered = "\n".join(["Transcript:", *rendered_entries])
        if len(rendered) > budget and budget > 0:
            rendered = tail_clip(raw, budget)
        details["rendered_entries"] = rendered_entries
        details["rendered_turns"] = sum(1 for line in rendered_entries if line.startswith("Turn "))
        return rendered, details

    def _group_turns(self, history):
        """执行 `_group_turns` 的内部逻辑。"""
        turns = OrderedDict()
        for item in history:
            turn_id = str(item.get("turn_id") or "legacy")
            turns.setdefault(turn_id, []).append(item)
        return turns

    def _compressed_turn_entries(self, turns, recent_turns, old_turn_line_limit=80):
        """执行 `_compressed_turn_entries` 的内部逻辑。"""
        entries = []
        seen_older_reads = set()
        history_items = [item for items in turns.values() for item in items]
        last_failed_tool = self._last_matching_tool(history_items, self._is_failed_tool)
        last_changed_tool = self._last_matching_tool(
            history_items, lambda item: bool(item.get("workspace_changed"))
        )
        retention = RetentionContext(
            recent_turns=recent_turns,
            last_failed_tool_event_id=str((last_failed_tool or {}).get("event_id", "")),
            last_changed_tool_event_id=str((last_changed_tool or {}).get("event_id", "")),
            changed_paths=self._current_changed_paths(),
        )
        policy = ContextRetentionPolicy()
        ledger = ReplacementLedger.from_session(getattr(self.agent, "session", {}))
        details = {
            "recent_window": len(recent_turns),
            "old_turn_line_limit": old_turn_line_limit,
            "older_entries_count": 0,
            "collapsed_duplicate_reads": 0,
            "reused_file_summary_count": 0,
            "summarized_tool_count": 0,
            "microcompact_artifact_refs": [],
            "microcompact_saved_chars": 0,
            "replacement_cache_hits": 0,
            "replacement_records_created": 0,
            "replacement_saved_chars": 0,
            "proposed_replacements": [],
        }
        for turn_id, items in turns.items():
            recent = turn_id in recent_turns and any(item.get("role") != "tool" for item in items)
            lines = [f"Turn {turn_id}:"]
            for item in items:
                if item.get("kind") == "compact_summary":
                    lines.extend(str(item.get("content", "")).splitlines())
                    continue
                if not recent and item.get("role") == "tool" and policy.should_render_tool_inline(item, retention):
                    lines.extend(self._render_item(item, 900))
                    continue
                if not recent and item.get("role") == "tool" and policy.can_replace_tool(item, retention):
                    replacement = self._ledger_replacement(item, ledger, details)
                    if replacement:
                        lines.append(replacement)
                        self._record_stub_metadata(item, replacement, details)
                        continue
                if not recent and item.get("role") == "tool" and item.get("name") == "read_file":
                    artifact_ref = str(item.get("artifact_ref", "")).strip()
                    if artifact_ref:
                        summary = self._summarize_old_tool_item(item)
                        lines.append(summary)
                        self._record_stub_metadata(item, summary, details)
                        continue
                    path = str(item.get("args", {}).get("path", "")).strip()
                    if path in seen_older_reads:
                        details["collapsed_duplicate_reads"] += 1
                        continue
                    seen_older_reads.add(path)
                    summary = self._reusable_file_summary(path)
                    if summary:
                        lines.append(f"{path} -> {summary}")
                        details["reused_file_summary_count"] += 1
                        continue
                if not recent and item.get("role") == "tool":
                    summary = self._summarize_old_tool_item(item)
                    lines.append(summary)
                    self._record_stub_metadata(item, summary, details)
                    continue
                lines.extend(self._render_item(item, 900 if recent else old_turn_line_limit))
            if not recent:
                details["older_entries_count"] += 1
            entries.append({"turn_id": turn_id, "lines": lines})
        return entries, details

    def _pressure_limits(self, pressure):
        """执行 `_pressure_limits` 的内部逻辑。"""
        tier = (
            str(getattr(pressure, "tier", "") or "")
            or str(getattr(pressure, "pressure_tier", "") or "tier0_observe")
        )
        return PRESSURE_LIMITS.get(tier, (3, 80))

    def _render_turn_lines(self, history, line_limit):
        """执行 `_render_turn_lines` 的内部逻辑。"""
        lines = []
        for turn_id, items in self._group_turns(history).items():
            lines.append(f"Turn {turn_id}:")
            for item in items:
                lines.extend(self._render_item(item, line_limit))
        return lines

    def _render_item(self, item, line_limit):
        """执行 `_render_item` 的内部逻辑。"""
        if item.get("kind") == "compact_summary":
            return str(item.get("content", "")).splitlines()
        if item.get("role") == "tool":
            prefix = f"[tool:{item.get('name', '')}] {json.dumps(item.get('args', {}), sort_keys=True)}"
            if item.get("media_refs"):
                content = tail_clip(item.get("content", ""), max(20, line_limit))
                return [prefix, *render_media_refs(item), content]
            content = tail_clip(item.get("content", ""), max(20, line_limit))
            return [prefix, content]
        return [f"[{item.get('role', '')}] {tail_clip(item.get('content', ''), line_limit)}"]

    def _reusable_file_summary(self, path):
        """执行 `_reusable_file_summary` 的内部逻辑。"""
        memory = getattr(self.agent, "memory", None)
        if memory is None or not hasattr(memory, "to_dict"):
            return ""
        summary = memory.to_dict().get("file_summaries", {}).get(str(path), {})
        return str(summary.get("summary", "")).strip()

    def _summarize_old_tool_item(self, item):
        """执行 `_summarize_old_tool_item` 的内部逻辑。"""
        artifact_ref = str(item.get("artifact_ref", "")).strip()
        if item.get("media_refs"):
            refs = render_media_refs(item)
            return " | ".join(refs) if refs else f"{item.get('name', 'tool')} media output"
        if artifact_ref:
            original_chars = int(item.get("original_chars", 0) or 0)
            return (
                f"{item.get('name', 'tool')} output saved: {artifact_ref}"
                f" ({original_chars} chars)"
            )
        if item.get("name") == "run_shell":
            command = str(item.get("args", {}).get("command", "")).strip() or "shell"
            lines = [line.strip() for line in str(item.get("content", "")).splitlines() if line.strip()]
            return f"{command} -> {' | '.join(lines[:3]) if lines else '(empty)'}"
        return self._render_item(item, 80)[0]

    def _current_changed_paths(self):
        """执行 `_current_changed_paths` 的内部逻辑。"""
        task_state = getattr(self.agent, "current_task_state", None)
        return {str(path) for path in getattr(task_state, "changed_paths", []) if str(path).strip()}

    def _ledger_replacement(self, item, ledger, details):
        """执行 `_ledger_replacement` 的内部逻辑。"""
        record = ledger.matching_record(item)
        if record:
            details["replacement_cache_hits"] += 1
            details["replacement_saved_chars"] += max(0, int(record.saved_chars or 0))
            return record.replacement_text
        summary = self._summarize_old_tool_item(item)
        proposed = ledger.proposed_record(item, summary)
        if proposed is None:
            return ""
        details["replacement_records_created"] += 1
        details["replacement_saved_chars"] += proposed.record.saved_chars
        details["proposed_replacements"].append(proposed.to_dict())
        return summary

    def _record_stub_metadata(self, item, summary, details):
        """执行 `_record_stub_metadata` 的内部逻辑。"""
        details["summarized_tool_count"] += 1
        artifact_ref = str(item.get("artifact_ref", "")).strip()
        if artifact_ref:
            details["microcompact_artifact_refs"].append(artifact_ref)
            details["microcompact_saved_chars"] += max(
                0, len(str(item.get("content", ""))) - len(str(summary))
            )

    @staticmethod
    def _last_matching_tool(history, predicate):
        """执行 `_last_matching_tool` 的内部逻辑。"""
        for item in reversed(history):
            if item.get("role") == "tool" and predicate(item):
                return item
        return None

    @staticmethod
    def _is_failed_tool(item):
        """执行 `_is_failed_tool` 的内部逻辑。"""
        status = str(item.get("tool_status", ""))
        return bool(status and status != "ok") or bool(item.get("tool_error_code"))


def should_render_tool_inline(item, context):
    """执行 `should_render_tool_inline` 的内部逻辑。"""
    return ContextRetentionPolicy().should_render_tool_inline(item, context)
