"""stdio transport implementation for MCP."""

import json
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout

from .mcp import McpServerConfig


class McpStdioClient:
    def __init__(self, config: McpServerConfig):
        self.config = config
        self.process = None
        self._next_id = 1
        self._lock = threading.RLock()

    def list_tools(self):
        return list(self._request("tools/list").get("tools", []))

    def call_tool(self, name, arguments):
        return self._request("tools/call", {"name": name, "arguments": dict(arguments or {})})

    def close(self):
        if self.process is not None:
            self.process.terminate()
            self.process = None

    def _start(self):
        if self.process is not None and self.process.poll() is None:
            return
        self.process = subprocess.Popen(
            [self.config.command, *self.config.args],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        self._request(
            "initialize",
            {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "clientInfo": {"name": "moka", "version": "0.3.0"},
            },
            initialize=False,
        )
        self._notify("notifications/initialized")

    def _notify(self, method):
        self.process.stdin.write(json.dumps({"jsonrpc": "2.0", "method": method}) + "\n")
        self.process.stdin.flush()

    def _request(self, method, params=None, *, initialize=True):
        with self._lock:
            if initialize:
                self._start()
            if self.process is None or self.process.poll() is not None:
                raise RuntimeError(f"MCP server unavailable: {self.config.name}")
            request_id = self._next_id
            self._next_id += 1
            payload = {"jsonrpc": "2.0", "id": request_id, "method": method}
            if params is not None:
                payload["params"] = params
            self.process.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
            self.process.stdin.flush()
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(self.process.stdout.readline)
                try:
                    line = future.result(timeout=self.config.timeout)
                except FutureTimeout as exc:
                    raise TimeoutError(f"MCP request timed out: {method}") from exc
            if not line:
                raise RuntimeError(f"MCP server exited during {method}")
            response = json.loads(line)
            if response.get("id") != request_id:
                raise RuntimeError(f"unexpected MCP response id for {method}")
            if "error" in response:
                raise RuntimeError(str(response["error"].get("message", "MCP error")))
            return dict(response.get("result", {}))
