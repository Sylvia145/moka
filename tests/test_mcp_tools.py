import sys
from pathlib import Path

from pico import Pico, SessionStore, WorkspaceContext
from pico.testing import ScriptedModelClient
from pico.tools import McpServerConfig


SERVER = '''
import json, sys
for line in sys.stdin:
    request = json.loads(line)
    method = request.get("method")
    if "id" not in request:
        continue
    if method == "initialize":
        result = {"protocolVersion": "2025-06-18", "capabilities": {}, "serverInfo": {"name": "mock", "version": "1"}}
    elif method == "tools/list":
        result = {"tools": [{"name": "echo", "description": "Echo text", "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}}]}
    elif method == "tools/call":
        result = {"content": [{"type": "text", "text": request["params"]["arguments"]["text"]}]}
    else:
        result = {}
    print(json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": result}), flush=True)
'''


def test_mcp_stdio_tool_uses_existing_permission_and_trace(tmp_path):
    script = tmp_path / "mock_mcp.py"
    script.write_text(SERVER, encoding="utf-8")
    (tmp_path / "README.md").write_text("demo\n", encoding="utf-8")
    workspace = WorkspaceContext.build(tmp_path)
    agent = Pico(
        model_client=ScriptedModelClient([]),
        workspace=workspace,
        session_store=SessionStore(tmp_path / ".pico" / "sessions"),
        approval_policy="auto",
        mcp_servers=(McpServerConfig("mock", sys.executable, (str(script),)),),
    )

    assert "mcp__mock__echo" in agent.tools
    assert "invalid arguments" in agent.run_tool("mcp__mock__echo", {})
    assert agent.run_tool("mcp__mock__echo", {"text": "hello"}) == "hello"

    agent.mcp_clients["mock"].close()
