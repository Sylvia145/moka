"""Pico 运行时实现模块。"""

import json
import subprocess
from pathlib import Path

from .workspace import IGNORED_PATH_NAMES


def collect_worker_artifacts(root, child, task_state):
    """执行 `collect_worker_artifacts` 的内部逻辑。"""
    run_dir = getattr(child, "current_run_dir", None)
    payload = {
        "run_id": str(getattr(task_state, "run_id", "") or ""),
        "run_dir": relative_path(root, run_dir),
        "report_path": relative_path(root, run_dir / "report.json" if run_dir else None),
        "trace_path": relative_path(root, run_dir / "trace.jsonl" if run_dir else None),
        "session_event_path": relative_path(root, getattr(getattr(child, "session_event_bus", None), "path", None)),
        "tool_error_codes": [],
        "changed_paths": list(getattr(task_state, "changed_paths", []) or []),
        "verification": dict(
            (getattr(task_state, "evidence_summaries", {}) or {}).get("verification_signal", {})
        ),
    }
    trace_path = run_dir / "trace.jsonl" if run_dir else None
    if trace_path and trace_path.exists():
        payload["tool_error_codes"] = trace_error_codes(trace_path)
    return payload


def trace_error_codes(trace_path):
    """执行 `trace_error_codes` 的内部逻辑。"""
    error_codes = []
    for line in trace_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("event") != "tool_executed":
            continue
        code = str(event.get("tool_error_code", "")).strip()
        if code and code not in error_codes:
            error_codes.append(code)
    return error_codes


def build_change_handoff(workspace_root, base_commit, artifacts):
    """Build review evidence from the isolated workspace, not model narration."""
    workspace_root = Path(workspace_root)
    changed_paths = list(artifacts.get("changed_paths", []))
    review_required = bool(base_commit)
    handoff = {
        "status": "pending_review" if review_required else "not_applicable",
        "review_required": review_required,
        "base_commit": str(base_commit or ""),
        "changed_paths": changed_paths,
        "diff_stat": "",
        "diff_paths": [],
        "diff_check_exit_code": None,
        "verification": dict(artifacts.get("verification", {})),
        "error_codes": list(artifacts.get("tool_error_codes", [])),
        "risk_flags": [],
    }
    if review_required:
        handoff.update(_git_diff_evidence(workspace_root, str(base_commit)))
        handoff["risk_flags"].append("human_review_required")
    if handoff["error_codes"]:
        handoff["risk_flags"].append("tool_errors_present")
    if handoff["verification"].get("state") not in {"passed", "verified"}:
        handoff["risk_flags"].append("verification_incomplete")
    return handoff


def _git_diff_evidence(workspace_root, base_commit):
    """执行 `_git_diff_evidence` 的内部逻辑。"""
    if not workspace_root.exists():
        return {}
    diff_paths = _reviewable_paths(
        _git_output(workspace_root, ["diff", "--name-only", base_commit]).splitlines()
    )
    untracked_paths = _git_untracked_paths(workspace_root)
    diff_stat = _git_output(workspace_root, ["diff", "--stat", base_commit])
    if untracked_paths:
        untracked_summary = "\n".join(f"  {path} | untracked" for path in untracked_paths)
        diff_stat = "\n".join(filter(None, [diff_stat, "Untracked files:", untracked_summary]))
    return {
        "diff_stat": diff_stat,
        "diff_paths": list(dict.fromkeys([*diff_paths, *untracked_paths])),
        "untracked_paths": untracked_paths,
        "diff_check_exit_code": _git_exit_code(workspace_root, ["diff", "--check", base_commit]),
    }


def _git_untracked_paths(workspace_root):
    """执行 `_git_untracked_paths` 的内部逻辑。"""
    return _reviewable_paths(
        _git_output(workspace_root, ["ls-files", "--others", "--exclude-standard"]).splitlines()
    )


def _reviewable_paths(paths):
    """执行 `_reviewable_paths` 的内部逻辑。"""
    return [path for path in paths if not any(part in IGNORED_PATH_NAMES for part in Path(path).parts)]


def _git_output(workspace_root, args):
    """执行 `_git_output` 的内部逻辑。"""
    result = subprocess.run(
        ["git", *args],
        cwd=workspace_root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    return result.stdout.strip()


def _git_exit_code(workspace_root, args):
    """执行 `_git_exit_code` 的内部逻辑。"""
    return subprocess.run(
        ["git", *args],
        cwd=workspace_root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    ).returncode


def relative_path(root, path):
    """执行 `relative_path` 的内部逻辑。"""
    if not path:
        return ""
    try:
        return str(path.relative_to(root).as_posix())
    except ValueError:
        return str(path)
