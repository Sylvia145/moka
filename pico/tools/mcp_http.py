"""Streamable HTTP transport for remote MCP servers.

This client intentionally does not retry `tools/call`: after a network failure,
the remote side may have already performed a non-idempotent action.
"""

import json
import os
import threading
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .mcp import McpServerConfig

MCP_PROTOCOL_VERSION = "2025-11-25"


class McpHttpError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code


class McpOutcomeUnknownError(McpHttpError):
    pass


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class McpStreamableHttpClient:
    def __init__(self, config: McpServerConfig):
        self.config = config
        self.url = _validate_url(config)
        self._next_id = 1
        self._lock = threading.RLock()
        self._session_id = None
        self._protocol_version = MCP_PROTOCOL_VERSION
        self._initialized = False
        self._opener = build_opener(_NoRedirect())

    def list_tools(self):
        return list(self._request("tools/list", retryable=True).get("tools", []))

    def call_tool(self, name, arguments):
        try:
            return self._request(
                "tools/call",
                {"name": name, "arguments": dict(arguments or {})},
                retryable=False,
            )
        except McpHttpError as exc:
            if exc.code in {"mcp_http_timeout", "mcp_http_server_error", "mcp_http_connect_failed"}:
                raise McpOutcomeUnknownError(
                    "mcp_outcome_unknown",
                    "remote tools/call may have executed; Moka did not retry it",
                ) from exc
            raise

    def close(self):
        self._session_id = None
        self._initialized = False

    def _initialize(self):
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
        self._request_raw(method, None, notification=True)

    def _request(self, method, params=None, *, retryable):
        with self._lock:
            attempts = max(0, int(self.config.max_retries)) if retryable else 0
            for attempt in range(attempts + 1):
                try:
                    if not self._initialized:
                        self._initialize()
                    return self._request_raw(method, params)
                except McpHttpError as exc:
                    if exc.code == "mcp_session_expired" and retryable and attempt < attempts:
                        self._reset_session()
                        continue
                    if exc.code in {"mcp_http_timeout", "mcp_http_connect_failed", "mcp_http_server_error"} and retryable and attempt < attempts:
                        continue
                    raise
            raise AssertionError("unreachable")

    def _request_raw(self, method, params, *, notification=False):
        request_id = None if notification else self._next_request_id()
        payload = {"jsonrpc": "2.0", "method": method}
        if request_id is not None:
            payload["id"] = request_id
        if params is not None:
            payload["params"] = params
        response, headers = self._post(payload, expect_body=not notification)
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

    def _post(self, payload, *, expect_body=True):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            "MCP-Protocol-Version": self._protocol_version,
        }
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
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

    def _next_request_id(self):
        request_id = self._next_id
        self._next_id += 1
        return request_id

    def _reset_session(self):
        self._session_id = None
        self._initialized = False


def _validate_url(config: McpServerConfig) -> str:
    if not config.url:
        raise ValueError(f"MCP HTTP server {config.name!r} requires url")
    parsed = urlparse(config.url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("MCP HTTP url must be an absolute http(s) URL")
    if parsed.scheme != "https" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("MCP HTTP requires HTTPS outside explicit localhost testing")
    return config.url


def _resolve_token(config: McpServerConfig) -> str:
    if not config.token_env:
        return ""
    token = os.environ.get(config.token_env, "")
    if not token:
        raise McpHttpError("mcp_http_unauthorized", f"missing credential environment variable: {config.token_env}")
    return token


def _read_limited(response, limit: int) -> bytes:
    size_limit = max(1, int(limit))
    data = response.read(size_limit + 1)
    if len(data) > size_limit:
        raise McpHttpError("mcp_response_too_large", "remote MCP response exceeded configured limit")
    return data


def _parse_response(data: bytes, content_type: str) -> list[dict]:
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
    try:
        message = json.loads(text)
    except json.JSONDecodeError as exc:
        raise McpHttpError("mcp_invalid_response", "remote MCP SSE event was not JSON") from exc
    if not isinstance(message, dict):
        raise McpHttpError("mcp_invalid_response", "remote MCP SSE event was not an object")
    return message


def _select_response(messages: list[dict], request_id: int) -> dict:
    for message in messages:
        if message.get("id") == request_id:
            return message
    raise McpHttpError("mcp_invalid_response", "remote MCP response id did not match request")
