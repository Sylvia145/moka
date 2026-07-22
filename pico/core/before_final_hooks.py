"""Pico 运行时实现模块。

Hooks are explicit extension points for project or benchmark policy. Core Pico
does not infer benchmark contracts from prompts; callers can register hooks
when they have structured expectations.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Literal

from .before_final_hook_summary import reduce_before_final_hook_summary as _reduce_hook_summary

HOOK_SUMMARY_SCHEMA = "pico.before_final_hook_summary.v1"
HOOK_ACTIONS = {"allow", "warn", "runtime_notice", "block"}


@dataclass(frozen=True)
class BeforeFinalContext:
    session_id: str
    run_id: str
    workspace_root: Path
    user_request: str
    proposed_final: str
    changed_paths: list[str]
    todo_changes: list[dict]
    evidence_summaries: dict
    trace_path: Path | None = None
    report_path: Path | None = None


@dataclass(frozen=True)
class BeforeFinalHookDecision:
    action: Literal["allow", "warn", "runtime_notice", "block"] = "allow"
    reason: str = ""
    message: str = ""
    hook: str = ""
    metadata: dict = field(default_factory=dict)


BeforeFinalHook = Callable[[BeforeFinalContext], BeforeFinalHookDecision | dict | None]


def run_before_final_hooks(agent, task_state, proposed_final):
    """执行 `run_before_final_hooks` 的内部逻辑。"""
    hooks = list(getattr(agent, "before_final_hooks", ()) or ())
    if not hooks:
        return {"action": "allow", "decisions": [], "hook_count": 0}

    context = BeforeFinalContext(
        session_id=str(agent.session.get("id", "")),
        run_id=str(task_state.run_id),
        workspace_root=Path(agent.root),
        user_request=str(task_state.user_request),
        proposed_final=str(proposed_final),
        changed_paths=list(task_state.changed_paths or []),
        todo_changes=list(task_state.todo_changes or []),
        evidence_summaries=dict(task_state.evidence_summaries or {}),
        trace_path=(agent.current_run_dir / "trace.jsonl") if agent.current_run_dir else None,
        report_path=(agent.current_run_dir / "report.json") if agent.current_run_dir else None,
    )

    decisions = [_decision_to_dict(_call_hook(hook, context), hook) for hook in hooks]
    actionable = [
        decision for decision in decisions if decision.get("action") in {"block", "runtime_notice", "warn"}
    ]
    selected = _select_decision(actionable)
    return {
        "schema_version": HOOK_SUMMARY_SCHEMA,
        "action": selected.get("action", "allow"),
        "reason": selected.get("reason", ""),
        "message": selected.get("message", ""),
        "hook": selected.get("hook", ""),
        "metadata": dict(selected.get("metadata", {}) or {}),
        "hook_count": len(hooks),
        "decisions": decisions,
    }


def reduce_before_final_hook_summary(summary, event):
    """执行 `reduce_before_final_hook_summary` 的内部逻辑。"""
    return _reduce_hook_summary(summary, event, HOOK_SUMMARY_SCHEMA)

def _call_hook(hook, context):
    """执行 `_call_hook` 的内部逻辑。"""
    try:
        return hook(context)
    except Exception as exc:  # 钩子属于策略扩展，不影响核心运行时稳定性。
        return BeforeFinalHookDecision(
            action="warn",
            reason="hook_error",
            message=f"Before-final hook failed: {exc}",
            hook=_hook_name(hook),
        )


def _decision_to_dict(decision, hook):
    """执行 `_decision_to_dict` 的内部逻辑。"""
    if decision is None:
        decision = BeforeFinalHookDecision(hook=_hook_name(hook))
    if isinstance(decision, BeforeFinalHookDecision):
        payload = {
            "action": decision.action,
            "reason": decision.reason,
            "message": decision.message,
            "hook": decision.hook or _hook_name(hook),
            "metadata": dict(decision.metadata or {}),
        }
    else:
        payload = dict(decision or {})
        payload.setdefault("hook", _hook_name(hook))
        payload.setdefault("metadata", {})
    action = str(payload.get("action", "allow"))
    if action not in HOOK_ACTIONS:
        action = "warn"
        payload["reason"] = payload.get("reason") or "invalid_hook_action"
        payload["message"] = payload.get("message") or "Before-final hook returned an invalid action."
    payload["action"] = action
    payload["reason"] = str(payload.get("reason", ""))
    payload["message"] = str(payload.get("message", ""))
    payload["hook"] = str(payload.get("hook", ""))
    payload["metadata"] = dict(payload.get("metadata", {}) or {})
    return payload


def _select_decision(decisions):
    """执行 `_select_decision` 的内部逻辑。"""
    if not decisions:
        return {"action": "allow"}
    for action in ("block", "runtime_notice", "warn"):
        for decision in decisions:
            if decision.get("action") == action:
                return decision
    return {"action": "allow"}


def _hook_name(hook):
    """执行 `_hook_name` 的内部逻辑。"""
    return getattr(hook, "__name__", hook.__class__.__name__)
