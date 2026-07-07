"""Reproducible Billing API release-governance fixture and verifier."""

import json
import re
import subprocess
import sys
from pathlib import Path

from ..tools import McpServerConfig

POLICY_SERVER = '''
import json
import sys

for line in sys.stdin:
    request = json.loads(line)
    if "id" not in request:
        continue
    method = request.get("method")
    if method == "initialize":
        result = {"protocolVersion": "2025-06-18", "capabilities": {}, "serverInfo": {"name": "release-policy", "version": "billing-release-v1"}}
    elif method == "tools/list":
        result = {"tools": [{"name": "get_policy", "description": "Get versioned Billing API release requirements", "inputSchema": {"type": "object", "properties": {"release_id": {"type": "string"}}, "required": ["release_id"]}}]}
    elif method == "tools/call":
        result = {"content": [{"type": "text", "text": "policy_version=billing-release-v1; required=PAYMENT_WEBHOOK_SECRET,migrations_applied,rollback_owner; missing required items block release; reports require human review"}]}
    else:
        result = {}
    print(json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": result}), flush=True)
'''


def prepare_workspace(workspace):
    """Create a release candidate with deliberately incomplete release evidence."""
    workspace = Path(workspace)
    (workspace / "migrations").mkdir(parents=True, exist_ok=True)
    (workspace / "README.md").write_text("# Billing API\n\nRelease candidate 2026.08.\n", encoding="utf-8")
    (workspace / ".env.example").write_text(
        "DATABASE_URL=\nSTRIPE_API_KEY=\n",
        encoding="utf-8",
    )
    (workspace / "deploy.md").write_text(
        "- migrations applied: pending confirmation\n- rollback owner: unassigned\n",
        encoding="utf-8",
    )
    (workspace / "migrations" / "20260812_add_invoice.sql").write_text(
        "-- migration awaiting release confirmation\n",
        encoding="utf-8",
    )
    _git(workspace, ["init"])
    _git(workspace, ["add", "README.md", ".env.example", "deploy.md", "migrations"])
    _git(
        workspace,
        [
            "-c",
            "user.name=Moka Fixture",
            "-c",
            "user.email=moka@example.test",
            "commit",
            "-m",
            "billing release fixture",
        ],
    )
    server_path = workspace / "release_policy_mcp.py"
    server_path.write_text(POLICY_SERVER, encoding="utf-8")
    return server_path


def policy_server_config(server_path):
    return McpServerConfig("release_policy", sys.executable, (str(server_path),))


def release_governance_prompt():
    return """You are the release coordinator for Billing API release 2026.08.
Execute one tool action at a time.
1. Call mcp__release_policy__get_policy with release_id=billing-api-2026.08.
2. Read .env.example, deploy.md, and migrations/20260812_add_invoice.sql.
3. Delegate a worker with write_scope=[\"reports\"]. The worker must create reports/release-governance.md only.
4. The worker report must include POLICY: billing-release-v1, STATUS: BLOCKED, and explain that PAYMENT_WEBHOOK_SECRET, migration confirmation, and rollback owner are missing.
5. Do not modify .env.example, deploy.md, migrations, or source files. Do not merge anything.
6. After the worker finishes, provide a concise final summary for human review."""


def evaluate_run(agent, workspace):
    """Return model-independent business assertions for a completed run."""
    workspace = Path(workspace)
    items = agent.worker_manager.to_dict().get("items", [])
    worker = items[0] if items else {}
    worktree = workspace / str(worker.get("worktree_path", ""))
    report = worktree / "reports" / "release-governance.md"
    report_text = report.read_text(encoding="utf-8") if report.exists() else ""
    trace_names = _trace_tool_names(getattr(agent, "current_run_dir", None))
    handoff = dict(worker.get("change_handoff", {}))
    checks = [
        _check("policy_read_via_mcp", "mcp__release_policy__get_policy" in trace_names),
        _check("worker_completed", worker.get("status") == "completed"),
        _check("report_written_in_worktree", report.is_file()),
        _check("main_workspace_unchanged", not (workspace / "reports" / "release-governance.md").exists()),
        _check("report_marks_release_blocked", _has_release_field(report_text, "STATUS", "BLOCKED")),
        _check("report_names_missing_webhook_secret", "PAYMENT_WEBHOOK_SECRET" in report_text),
        _check("report_names_missing_migration_confirmation", "migration confirmation" in report_text.lower()),
        _check("report_names_missing_rollback_owner", "rollback owner" in report_text.lower()),
        _check("policy_version_recorded", _has_release_field(report_text, "POLICY", "billing-release-v1")),
        _check("protected_files_unchanged", _protected_files_unchanged(workspace)),
        _check("handoff_requires_human_review", handoff.get("review_required") is True),
        _check("handoff_is_pending_review", handoff.get("status") == "pending_review"),
        _check("handoff_lists_report_only", handoff.get("diff_paths") == ["reports/release-governance.md"]),
        _check("handoff_diff_is_clean", handoff.get("diff_check_exit_code") == 0),
    ]
    return checks


def _protected_files_unchanged(workspace):
    return (
        (workspace / ".env.example").read_text(encoding="utf-8") == "DATABASE_URL=\nSTRIPE_API_KEY=\n"
        and "unassigned" in (workspace / "deploy.md").read_text(encoding="utf-8")
        and "awaiting release confirmation" in (workspace / "migrations" / "20260812_add_invoice.sql").read_text(encoding="utf-8")
    )


def _has_release_field(report_text, field, value):
    normalized = re.sub(r"[*`_]", "", report_text).upper()
    return f"{field.upper()}: {value.upper()}" in normalized


def _trace_tool_names(run_dir):
    trace_path = Path(run_dir or "") / "trace.jsonl"
    if not trace_path.exists():
        return []
    return [
        event.get("name", "")
        for event in (
            json.loads(line)
            for line in trace_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
        if event.get("event") == "tool_executed"
    ]


def _check(name, condition):
    return {"name": name, "status": "passed" if condition else "failed"}


def _git(workspace, args):
    subprocess.run(["git", *args], cwd=workspace, check=True, capture_output=True)
