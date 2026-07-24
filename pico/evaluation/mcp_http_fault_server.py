"""Pico 运行时实现模块。

可复用的本地 MCP streamable-HTTP 故障注入服务器，供
tests/test_mcp_http.py 与 scripts/mcp_http_fault_injection.py 共同消费。

除了既有 mode 故障（timeout/disconnect/truncated/server_error/large）外，
还支持幂等键去重：

- ``dedup_idempotent``：客户端带 ``Idempotency-Key`` 头时，服务端先写入
  commit marker 再注入故障；重复 key 返回预备结果而不重复执行副作用。
- ``fail_first_call``：仅首个 ``tools/call`` 注入当前 mode 故障，后续按
  json 正常处理，用于验证客户端重试后恢复。

生产服务端必须为缓存加 TTL 并做容量限制；此处为确定性测试/基准脚本，
不做回收。
"""

import json
import socket
import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


@contextmanager
def http_mcp_server(
    mode="json",
    *,
    expire_first=False,
    list_failures=0,
    require_token=None,
    dedup_idempotent=True,
    fail_first_call=False,
):
    """执行 `http_mcp_server` 的内部逻辑。"""
    state = {
        "mode": mode,
        "expire_first": expire_first,
        "require_token": require_token,
        "dedup_idempotent": bool(dedup_idempotent),
        "fail_first_call": bool(fail_first_call),
        "first_call_consumed": False,
        "calls": [],
        "initialize_count": 0,
        "list_failures": int(list_failures),
        "tool_call_count": 0,
        "side_effects": [],
        "idempotent_cache": {},
        "idempotent_lock": threading.Lock(),
        "dedup_hits": 0,
        "idempotent_keys_seen": [],
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
                if state["list_failures"] > 0:
                    state["list_failures"] -= 1
                    self.send_response(503)
                    self.end_headers()
                    return
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
                text = request["params"]["arguments"].get("text", "")
                result = {"content": [{"type": "text", "text": text}]}
                idem = self.headers.get("Idempotency-Key")
                if idem and state["dedup_idempotent"]:
                    with state["idempotent_lock"]:
                        if idem in state["idempotent_cache"]:
                            state["dedup_hits"] += 1
                            return self._send_json(request["id"], state["idempotent_cache"][idem])
                        state["idempotent_keys_seen"].append(idem)
                        # commit marker：先写入预备结果，再注入故障。重复 key 直接返回
                        # 该结果而不重复执行副作用，这是幂等重试"精确一次"的关键。
                        state["idempotent_cache"][idem] = result
                if state["fail_first_call"] and state["first_call_consumed"]:
                    effective = "json"
                else:
                    state["first_call_consumed"] = True
                    effective = state["mode"]
                state["side_effects"].append({"request_id": request["id"], "text": text})
                if effective == "timeout":
                    time.sleep(0.2)
                elif effective == "disconnect":
                    self._close_connection()
                    return
                elif effective == "truncated":
                    self._send_truncated_json(request["id"], result)
                    return
                elif effective == "server_error":
                    self.send_response(503)
                    self.end_headers()
                    return
                elif effective == "large":
                    self._send_large()
                    return
                return self._send_json(request["id"], result)
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
            # 体积需大于 initialize(约140B)/tools/list(约197B) 的正常响应，
            # 使 max_response_bytes 只拦截 large 分支。
            body = b"x" * 8192
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_truncated_json(self, request_id, result):
            """发送声明长度大于实际内容的响应，模拟副作用提交后的响应中断。"""
            body = json.dumps({"jsonrpc": "2.0", "id": request_id, "result": result}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body[: max(1, len(body) // 2)])
            self.wfile.flush()
            self._close_connection()

        def _close_connection(self):
            """在响应完成前关闭连接，保留服务器已提交副作用的事实。"""
            self.close_connection = True
            try:
                self.connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            self.connection.close()

        def log_message(self, _format, *_args):
            """执行 `log_message` 的内部逻辑。"""
            return

    class _SilentServer(ThreadingHTTPServer):
        def handle_error(self, request, client_address):
            """静默 disconnect/截断场景下线程写响应时的连接中断，保持输出干净。"""
            return

    server = _SilentServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield state, f"http://127.0.0.1:{server.server_port}/mcp"
    finally:
        server.shutdown()
        thread.join(timeout=1)
        server.server_close()
