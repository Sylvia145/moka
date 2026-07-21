"""Pico 自动化测试模块。"""
import json
import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from pico import Pico, SessionStore, WorkspaceContext
from pico.testing import ScriptedModelClient
from pico.tools import McpServerConfig
from pico.tools.mcp import create_mcp_client
from pico.tools.mcp_http import McpHttpError, McpOutcomeUnknownError


@contextmanager
def http_mcp_server(mode="json", *, expire_first=False, require_token=None):
    """执行 `http_mcp_server` 的内部逻辑。"""
    state = {
        "mode": mode,
        "expire_first": expire_first,
        "require_token": require_token,
        "calls": [],
        "initialize_count": 0,
        "tool_call_count": 0,
    }

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            """执行 `do_POST` 的内部逻辑。"""
            length = int(self.headers.get("Content-Length", 0))
            request = json.loads(self.rfile.read(length).decode("utf-8"))
            state["calls"].append({"request": request, "headers": dict(self.headers)})
            if state["require_token"] and self.headers.get("Authorization") != f"Bearer {state['require_token']}":
                self.send_response(401)
                self.end_headers()
                return
            method = request["method"]
            if method == "initialize":
                state["initialize_count"] += 1
                return self._send_json(
                    request.get("id"),
                    {"protocolVersion": "2025-11-25", "capabilities": {}, "serverInfo": {"name": "http", "version": "1"}},
                    session="session-1",
                )
            if "id" not in request:
                self.send_response(202)
                self.end_headers()
                return
            if state["expire_first"] and method == "tools/list":
                state["expire_first"] = False
                self.send_response(404)
                self.end_headers()
                return
            if method == "tools/list":
                result = {
                    "tools": [
                        {
                            "name": "echo",
                            "description": "Echo text",
                            "inputSchema": {
                                "type": "object",
                                "properties": {"text": {"type": "string"}},
                                "required": ["text"],
                            },
                        }
                    ]
                }
                if state["mode"] == "sse":
                    return self._send_sse(request["id"], result)
                if state["mode"] == "large":
                    return self._send_large()
                return self._send_json(request["id"], result)
            if method == "tools/call":
                state["tool_call_count"] += 1
                if state["mode"] == "timeout":
                    time.sleep(0.2)
                text = request["params"]["arguments"].get("text", "")
                return self._send_json(request["id"], {"content": [{"type": "text", "text": text}]})
            self._send_json(request["id"], {})

        def _send_json(self, request_id, result, session=None):
            """执行 `_send_json` 的内部逻辑。"""
            body = json.dumps({"jsonrpc": "2.0", "id": request_id, "result": result}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            if session:
                self.send_header("Mcp-Session-Id", session)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_sse(self, request_id, result):
            """执行 `_send_sse` 的内部逻辑。"""
            body = f"event: message\ndata: {json.dumps({'jsonrpc': '2.0', 'id': request_id, 'result': result})}\n\n".encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_large(self):
            """执行 `_send_large` 的内部逻辑。"""
            body = b"x" * 256
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format, *_args):
            """执行 `log_message` 的内部逻辑。"""
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield state, f"http://127.0.0.1:{server.server_port}/mcp"
    finally:
        server.shutdown()
        thread.join(timeout=1)
        server.server_close()


def _config(url, **kwargs):
    """执行 `_config` 的内部逻辑。"""
    return McpServerConfig("remote", transport="streamable_http", url=url, timeout=0.05, **kwargs)


def test_streamable_http_json_registers_tools_in_existing_registry(tmp_path):
    """执行 `test_streamable_http_json_registers_tools_in_existing_registry` 的内部逻辑。"""
    with http_mcp_server() as (state, url):
        workspace = WorkspaceContext.build(tmp_path)
        agent = Pico(
            model_client=ScriptedModelClient([]),
            workspace=workspace,
            session_store=SessionStore(tmp_path / ".pico" / "sessions"),
            approval_policy="auto",
            mcp_servers=(_config(url),),
        )

        assert "mcp__remote__echo" in agent.tools
        assert agent.run_tool("mcp__remote__echo", {"text": "hello"}) == "hello"
        assert state["calls"][0]["request"]["method"] == "initialize"
        assert state["calls"][1]["request"]["method"] == "notifications/initialized"
        assert state["calls"][2]["request"]["method"] == "tools/list"
        assert state["calls"][3]["headers"]["Mcp-Session-Id"] == "session-1"
        agent.mcp_clients["remote"].close()


def test_streamable_http_supports_sse_tool_discovery():
    """执行 `test_streamable_http_supports_sse_tool_discovery` 的内部逻辑。"""
    with http_mcp_server("sse") as (_state, url):
        client = create_mcp_client(_config(url))

        assert client.list_tools()[0]["name"] == "echo"
        client.close()


def test_streamable_http_recovers_expired_session_for_read_operation():
    """执行 `test_streamable_http_recovers_expired_session_for_read_operation` 的内部逻辑。"""
    with http_mcp_server(expire_first=True) as (state, url):
        client = create_mcp_client(_config(url, max_retries=1))

        assert client.list_tools()[0]["name"] == "echo"
        assert state["initialize_count"] == 2
        client.close()


def test_streamable_http_does_not_retry_side_effect_when_result_is_unknown():
    """执行 `test_streamable_http_does_not_retry_side_effect_when_result_is_unknown` 的内部逻辑。"""
    with http_mcp_server("timeout") as (state, url):
        client = create_mcp_client(_config(url, max_retries=3))

        with pytest.raises(McpOutcomeUnknownError, match="mcp_outcome_unknown"):
            client.call_tool("echo", {"text": "write once"})

        assert state["tool_call_count"] == 1
        client.close()


def test_streamable_http_outcome_unknown_is_preserved_in_agent_trace_metadata(tmp_path):
    """执行 `test_streamable_http_outcome_unknown_is_preserved_in_agent_trace_metadata` 的内部逻辑。"""
    with http_mcp_server("timeout") as (_state, url):
        agent = Pico(
            model_client=ScriptedModelClient([]),
            workspace=WorkspaceContext.build(tmp_path),
            session_store=SessionStore(tmp_path / ".pico" / "sessions"),
            approval_policy="auto",
            mcp_servers=(_config(url),),
        )

        assert "mcp_outcome_unknown" in agent.run_tool("mcp__remote__echo", {"text": "write once"})
        assert agent._last_tool_result_metadata["tool_error_code"] == "mcp_outcome_unknown"
        agent.mcp_clients["remote"].close()


def test_streamable_http_uses_environment_token_without_exposing_value(monkeypatch):
    """执行 `test_streamable_http_uses_environment_token_without_exposing_value` 的内部逻辑。"""
    token = "moka-test-token-not-for-artifacts"
    monkeypatch.setenv("MOKA_REMOTE_TOKEN", token)
    with http_mcp_server(require_token=token) as (state, url):
        client = create_mcp_client(_config(url, token_env="MOKA_REMOTE_TOKEN"))

        assert client.list_tools()[0]["name"] == "echo"
        assert state["calls"][0]["headers"]["Authorization"] == f"Bearer {token}"
        client.close()

    assert token not in str(client.config)
    monkeypatch.delenv("MOKA_REMOTE_TOKEN")


def test_streamable_http_limits_response_size():
    """执行 `test_streamable_http_limits_response_size` 的内部逻辑。"""
    with http_mcp_server("large") as (_state, url):
        client = create_mcp_client(_config(url, max_response_bytes=64))

        with pytest.raises(McpHttpError, match="mcp_response_too_large"):
            client.list_tools()
        client.close()


def test_streamable_http_rejects_non_local_plain_http():
    """执行 `test_streamable_http_rejects_non_local_plain_http` 的内部逻辑。"""
    with pytest.raises(ValueError, match="requires HTTPS"):
        create_mcp_client(McpServerConfig("unsafe", transport="http", url="http://example.com/mcp"))


def test_streamable_http_does_not_expose_rejected_token(monkeypatch):
    """执行 `test_streamable_http_does_not_expose_rejected_token` 的内部逻辑。"""
    token = "moka-token-that-must-not-appear-in-errors"
    monkeypatch.setenv("MOKA_BAD_TOKEN", token)
    with http_mcp_server(require_token="different-token") as (_state, url):
        client = create_mcp_client(_config(url, token_env="MOKA_BAD_TOKEN"))

        with pytest.raises(McpHttpError, match="mcp_http_unauthorized") as error:
            client.list_tools()

    assert token not in str(error.value)
    monkeypatch.delenv("MOKA_BAD_TOKEN")
