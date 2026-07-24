"""Pico 运行时实现模块。

This client does not retry `tools/call` by default: after a network failure,
the remote side may have already performed a non-idempotent action. When
`McpServerConfig.max_idempotent_retries > 0`, Moka retries an outcome-unknown
`tools/call` with the same `Idempotency-Key` header, so a cooperating server
can deduplicate and keep the side effect exactly-once.
"""

import json
import os
import secrets
import threading
from http.client import IncompleteRead, RemoteDisconnected
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .mcp import McpServerConfig

MCP_PROTOCOL_VERSION = "2025-11-25"

# tools/call 的结果未知四类：请求可能已送达远端、副作用可能已提交，但结果无法确认。
# 只有这四类允许幂等键安全重试；其余错误（unauthorized / session_expired /
# redirect_blocked / response_too_large / remote_error）是确定性拒绝，永不重试。
_UNKNOWN_OUTCOME_CODES = frozenset({
    "mcp_http_timeout",
    "mcp_http_server_error",
    "mcp_http_connect_failed",
    "mcp_invalid_response",
})


class McpHttpError(RuntimeError):
    def __init__(self, code: str, message: str):
        """初始化对象状态。"""
        super().__init__(f"{code}: {message}")
        self.code = code


class McpOutcomeUnknownError(McpHttpError):
    def __init__(self, code: str, message: str, *, cause_code: str):
        """保留安全对外错误码，同时记录触发结果未知的底层分类。"""
        super().__init__(code, message)
        self.cause_code = cause_code


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        """执行 `redirect_request` 的内部逻辑。"""
        return


class McpStreamableHttpClient:
    def __init__(self, config: McpServerConfig):
        """初始化对象状态。"""
        self.config = config
        self.url = _validate_url(config)
        self._next_id = 1
        self._lock = threading.RLock()
        self._session_id = None
        self._protocol_version = MCP_PROTOCOL_VERSION
        self._initialized = False
        self._opener = build_opener(_NoRedirect())
        self.last_idempotent_retries = 0

    def list_tools(self):
        """执行 `list_tools` 的内部逻辑。"""
        return list(self._request("tools/list", retryable=True).get("tools", []))

    def call_tool(self, name, arguments):
        """执行 `call_tool` 的内部逻辑。"""
        params = {"name": name, "arguments": dict(arguments or {})}
        max_idem = max(0, int(self.config.max_idempotent_retries))
        # 幂等键属于一次逻辑调用，而非 tool+参数签名：两个内容相同的业务写入
        # 仍必须可以独立执行；仅本次调用的内部重试复用该 key。
        key = _new_idempotency_key() if max_idem > 0 else None
        self.last_idempotent_retries = 0
        for attempt in range(max_idem + 1):
            try:
                return self._request(
                    "tools/call",
                    params,
                    retryable=False,
                    idempotency_key=key,
                )
            except McpHttpError as exc:
                if exc.code in _UNKNOWN_OUTCOME_CODES and attempt < max_idem:
                    self.last_idempotent_retries += 1
                    continue
                if exc.code in _UNKNOWN_OUTCOME_CODES:
                    if self.last_idempotent_retries:
                        msg = (
                            "remote tools/call may have executed; Moka retried "
                            f"{self.last_idempotent_retries} time(s) with the same idempotency key"
                        )
                    else:
                        msg = "remote tools/call may have executed; Moka did not retry it"
                    raise McpOutcomeUnknownError(
                        "mcp_outcome_unknown",
                        msg,
                        cause_code=exc.code,
                    ) from exc
                raise
        raise AssertionError("unreachable")

    def close(self):
        """执行 `close` 的内部逻辑。"""
        self._session_id = None
        self._initialized = False

    def _initialize(self):
        """执行 `_initialize` 的内部逻辑。"""
        result = self._request_raw(
            "initialize",
            {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "moka", "version": "0.3.0"},
            },
        )
        self._protocol_version = str(result.get("protocolVersion") or MCP_PROTOCOL_VERSION)
        self._initialized = True
        self._notify("notifications/initialized")

    def _notify(self, method):
        """执行 `_notify` 的内部逻辑。"""
        self._request_raw(method, None, notification=True)

    def _request(self, method, params=None, *, retryable, idempotency_key=None):
        """执行 `_request` 的内部逻辑。"""
        with self._lock:
            attempts = max(0, int(self.config.max_retries)) if retryable else 0
            for attempt in range(attempts + 1):
                try:
                    if not self._initialized:
                        self._initialize()
                    return self._request_raw(method, params, idempotency_key=idempotency_key)
                except McpHttpError as exc:
                    if exc.code == "mcp_session_expired" and retryable and attempt < attempts:
                        self._reset_session()
                        continue
                    if exc.code in {"mcp_http_timeout", "mcp_http_connect_failed", "mcp_http_server_error"} and retryable and attempt < attempts:
                        continue
                    raise
            raise AssertionError("unreachable")

    def _request_raw(self, method, params, *, notification=False, idempotency_key=None):
        """执行 `_request_raw` 的内部逻辑。"""
        request_id = None if notification else self._next_request_id()
        payload = {"jsonrpc": "2.0", "method": method}
        if request_id is not None:
            payload["id"] = request_id
        if params is not None:
            payload["params"] = params
        response, headers = self._post(
            payload,
            expect_body=not notification,
            idempotency_key=idempotency_key,
        )
        session_id = headers.get("Mcp-Session-Id")
        if session_id:
            self._session_id = session_id
        if notification:
            return {}
        message = _select_response(response, request_id)
        if "error" in message:
            error = message["error"]
            raise McpHttpError("mcp_remote_error", str(error.get("message", "MCP error")))
        return dict(message.get("result", {}))

    def _post(self, payload, *, expect_body=True, idempotency_key=None):
        """执行 `_post` 的内部逻辑。"""
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            "MCP-Protocol-Version": self._protocol_version,
        }
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        token = _resolve_token(self.config)
        if token:
            headers["Authorization"] = f"Bearer {token}"
        request = Request(self.url, data=body, headers=headers, method="POST")
        try:
            with self._opener.open(request, timeout=float(self.config.timeout)) as response:
                data = _read_limited(response, self.config.max_response_bytes)
                if not expect_body and not data:
                    return [], response.headers
                return _parse_response(data, response.headers.get_content_type()), response.headers
        except HTTPError as exc:
            if exc.code == 401:
                raise McpHttpError("mcp_http_unauthorized", "remote server rejected credentials") from exc
            if exc.code in {404, 410} and self._session_id:
                raise McpHttpError("mcp_session_expired", "remote MCP session expired") from exc
            if 500 <= exc.code <= 599:
                raise McpHttpError("mcp_http_server_error", f"remote server returned HTTP {exc.code}") from exc
            if 300 <= exc.code <= 399:
                raise McpHttpError("mcp_http_redirect_blocked", "remote MCP redirect was rejected") from exc
            raise McpHttpError("mcp_http_error", f"remote server returned HTTP {exc.code}") from exc
        except TimeoutError as exc:
            raise McpHttpError("mcp_http_timeout", "remote MCP request timed out") from exc
        except URLError as exc:
            raise McpHttpError("mcp_http_connect_failed", "remote MCP connection failed") from exc
        except (IncompleteRead, RemoteDisconnected, ConnectionError, OSError) as exc:
            raise McpHttpError(
                "mcp_http_connect_failed",
                "remote MCP connection or response was interrupted",
            ) from exc

    def _next_request_id(self):
        """执行 `_next_request_id` 的内部逻辑。"""
        request_id = self._next_id
        self._next_id += 1
        return request_id

    def _reset_session(self):
        """执行 `_reset_session` 的内部逻辑。"""
        self._session_id = None
        self._initialized = False


def _validate_url(config: McpServerConfig) -> str:
    """执行 `_validate_url` 的内部逻辑。"""
    if not config.url:
        raise ValueError(f"MCP HTTP server {config.name!r} requires url")
    parsed = urlparse(config.url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("MCP HTTP url must be an absolute http(s) URL")
    if parsed.scheme != "https" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("MCP HTTP requires HTTPS outside explicit localhost testing")
    return config.url


def _resolve_token(config: McpServerConfig) -> str:
    """执行 `_resolve_token` 的内部逻辑。"""
    if not config.token_env:
        return ""
    token = os.environ.get(config.token_env, "")
    if not token:
        raise McpHttpError("mcp_http_unauthorized", f"missing credential environment variable: {config.token_env}")
    return token


def _read_limited(response, limit: int) -> bytes:
    """执行 `_read_limited` 的内部逻辑。"""
    size_limit = max(1, int(limit))
    data = response.read(size_limit + 1)
    if len(data) > size_limit:
        raise McpHttpError("mcp_response_too_large", "remote MCP response exceeded configured limit")
    return data


def _parse_response(data: bytes, content_type: str) -> list[dict]:
    """执行 `_parse_response` 的内部逻辑。"""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise McpHttpError("mcp_invalid_response", "remote MCP response was not UTF-8") from exc
    if content_type == "text/event-stream":
        return _parse_sse(text)
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise McpHttpError("mcp_invalid_response", "remote MCP response was not JSON") from exc
    return [parsed] if isinstance(parsed, dict) else list(parsed)


def _parse_sse(text: str) -> list[dict]:
    """执行 `_parse_sse` 的内部逻辑。"""
    messages = []
    data_lines = []
    for line in text.splitlines():
        if not line:
            if data_lines:
                messages.append(_parse_sse_message("\n".join(data_lines)))
                data_lines = []
            continue
        if line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
    if data_lines:
        messages.append(_parse_sse_message("\n".join(data_lines)))
    if not messages:
        raise McpHttpError("mcp_invalid_response", "remote MCP SSE response had no data events")
    return messages


def _parse_sse_message(text: str) -> dict:
    """执行 `_parse_sse_message` 的内部逻辑。"""
    try:
        message = json.loads(text)
    except json.JSONDecodeError as exc:
        raise McpHttpError("mcp_invalid_response", "remote MCP SSE event was not JSON") from exc
    if not isinstance(message, dict):
        raise McpHttpError("mcp_invalid_response", "remote MCP SSE event was not an object")
    return message


def _select_response(messages: list[dict], request_id: int) -> dict:
    """执行 `_select_response` 的内部逻辑。"""
    for message in messages:
        if message.get("id") == request_id:
            return message
    raise McpHttpError("mcp_invalid_response", "remote MCP response id did not match request")


def _new_idempotency_key() -> str:
    """为一次逻辑 tools/call 生成不可预测的 256 位幂等键。"""
    return secrets.token_hex(32)
