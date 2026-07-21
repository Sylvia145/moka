"""Pico 运行时实现模块。"""

import json
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

POLICY_TEXT = (
    "policy_version=billing-release-v1; "
    "required=PAYMENT_WEBHOOK_SECRET,migrations_applied,rollback_owner; "
    "missing required items block release; reports require human review"
)


@contextmanager
def release_policy_http_server(*, response_mode="json"):
    """Run an independent HTTP MCP policy service for a deterministic test."""

    state = {"requests": [], "response_mode": response_mode}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            """执行 `do_POST` 的内部逻辑。"""
            length = int(self.headers.get("Content-Length", 0))
            request = json.loads(self.rfile.read(length).decode("utf-8"))
            state["requests"].append(request)
            method = request.get("method")
            if method == "initialize":
                self._send_json(
                    request["id"],
                    {
                        "protocolVersion": "2025-11-25",
                        "capabilities": {},
                        "serverInfo": {"name": "release-policy", "version": "billing-release-v1"},
                    },
                    session="release-policy-session",
                )
                return
            if "id" not in request:
                self.send_response(202)
                self.end_headers()
                return
            if method == "tools/list":
                result = {
                    "tools": [
                        {
                            "name": "get_policy",
                            "description": "Get versioned Billing API release requirements",
                            "annotations": {"readOnlyHint": True},
                            "inputSchema": {
                                "type": "object",
                                "properties": {"release_id": {"type": "string"}},
                                "required": ["release_id"],
                            },
                        }
                    ]
                }
                if state["response_mode"] == "sse":
                    self._send_sse(request["id"], result)
                else:
                    self._send_json(request["id"], result)
                return
            if method == "tools/call":
                self._send_json(request["id"], {"content": [{"type": "text", "text": POLICY_TEXT}]})
                return
            self._send_json(request["id"], {})

        def _send_json(self, request_id, result, session=None):
            """执行 `_send_json` 的内部逻辑。"""
            body = json.dumps({"jsonrpc": "2.0", "id": request_id, "result": result}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            if session:
                self.send_header("Mcp-Session-Id", session)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_sse(self, request_id, result):
            """执行 `_send_sse` 的内部逻辑。"""
            body = f"data: {json.dumps({'jsonrpc': '2.0', 'id': request_id, 'result': result})}\n\n".encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
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
        yield f"http://127.0.0.1:{server.server_port}/mcp", state
    finally:
        server.shutdown()
        thread.join(timeout=1)
        server.server_close()
