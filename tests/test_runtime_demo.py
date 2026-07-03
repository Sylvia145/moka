import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_runtime_demo_connects_mcp_worker_and_trace(tmp_path):
    output = tmp_path / "runtime-demo.json"
    completed = subprocess.run(
        [sys.executable, "scripts/run_agent_runtime_demo.py", "--output", str(output)],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    payload = json.loads(completed.stdout)

    assert payload["status"] == "passed"
    assert payload["mcp_tool_called"] is True
    assert payload["worker_status"] == "completed"
    assert payload["worktree_isolated"] is True
    assert payload["written_content"] == "Release notes require a verification section.\n"
    assert "mcp__policy__get_release_rule" in payload["trace_tool_names"]
    assert payload["worker_result_contract"]["changed_paths"] == ["notes/release.md"]
