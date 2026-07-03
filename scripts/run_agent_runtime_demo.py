#!/usr/bin/env python3
"""Run a deterministic end-to-end demo of the Agent runtime."""

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pico import Pico, SessionStore, WorkspaceContext
from pico.testing import ScriptedModelClient
from pico.tools import McpServerConfig

POLICY_SERVER = '''
import json
import sys

for line in sys.stdin:
    request = json.loads(line)
    if "id" not in request:
        continue
    method = request.get("method")
    if method == "initialize":
        result = {"protocolVersion": "2025-06-18", "capabilities": {}, "serverInfo": {"name": "policy", "version": "1"}}
    elif method == "tools/list":
        result = {"tools": [{"name": "get_release_rule", "description": "Return the release-note rule", "inputSchema": {"type": "object", "properties": {"topic": {"type": "string"}}, "required": ["topic"]}}]}
    elif method == "tools/call":
        result = {"content": [{"type": "text", "text": "Release notes require a verification section."}]}
    else:
        result = {}
    print(json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": result}), flush=True)
'''


def _read_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def run_demo() -> dict:
    with tempfile.TemporaryDirectory(prefix="moka-runtime-demo-") as temp_dir:
        root = Path(temp_dir)
        (root / "README.md").write_text("# Demo repository\n", encoding="utf-8")
        subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
        subprocess.run(["git", "add", "README.md"], cwd=root, check=True, capture_output=True)
        subprocess.run(
            [
                "git",
                "-c",
                "user.name=Moka Demo",
                "-c",
                "user.email=moka@example.test",
                "commit",
                "-m",
                "demo fixture",
            ],
            cwd=root,
            check=True,
            capture_output=True,
        )
        server_path = root / "policy_mcp.py"
        server_path.write_text(POLICY_SERVER, encoding="utf-8")
        agent = Pico(
            model_client=ScriptedModelClient(
                [
                    '<tool>{"name":"mcp__policy__get_release_rule","args":{"topic":"release-notes"}}</tool>',
                    '<tool>{"name":"agent","args":{"description":"Write release note","prompt":"Create notes/release.md with the approved release-note rule.","subagent_type":"worker","write_scope":["notes"]}}</tool>',
                    '<tool name="write_file" path="notes/release.md"><content>Release notes require a verification section.\n</content></tool>',
                    "<final>Release note was written in the isolated worktree.</final>",
                    "<final>Release-note task completed and verified.</final>",
                ]
            ),
            workspace=WorkspaceContext.build(root),
            session_store=SessionStore(root / ".pico" / "sessions"),
            approval_policy="auto",
            max_steps=5,
            mcp_servers=(McpServerConfig("policy", sys.executable, (str(server_path),)),),
        )
        try:
            final_answer = agent.ask("Apply the external release-note rule using an isolated worker.")
            report = json.loads((agent.current_run_dir / "report.json").read_text(encoding="utf-8"))
            events = _read_jsonl(agent.current_run_dir / "trace.jsonl")
            worker = report["workers"]["items"][0]
            worktree = root / worker["worktree_path"]
            note = worktree / "notes" / "release.md"
            return {
                "status": "passed",
                "final_answer": final_answer,
                "mcp_tool_called": any(event.get("name") == "mcp__policy__get_release_rule" for event in events),
                "worker_status": worker["status"],
                "worker_result_contract": worker["result_contract"],
                "worktree_isolated": note.exists() and not (root / "notes" / "release.md").exists(),
                "written_content": note.read_text(encoding="utf-8") if note.exists() else "",
                "trace_tool_names": [event.get("name") for event in events if event.get("event") == "tool_executed"],
            }
        finally:
            agent.mcp_clients["policy"].close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Optional JSON report path")
    args = parser.parse_args(argv)
    payload = run_demo()
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
