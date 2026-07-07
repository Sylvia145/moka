"""MCP configuration, transport factory, and Tool Registry adapter."""

from dataclasses import dataclass
from typing import Protocol

from .base import RegisteredTool, ToolResult


@dataclass(frozen=True)
class McpServerConfig:
    """Connection configuration for one local or remote MCP server.

    The first three fields preserve the original stdio positional API. Remote
    credentials are referenced by environment-variable name, never stored in
    this configuration object as a token value.
    """

    name: str
    command: str = ""
    args: tuple[str, ...] = ()
    timeout: float = 15.0
    transport: str = "stdio"
    url: str | None = None
    token_env: str | None = None
    max_response_bytes: int = 1_000_000
    max_retries: int = 1


class McpClient(Protocol):
    def list_tools(self) -> list[dict]: ...

    def call_tool(self, name: str, arguments: dict) -> dict: ...

    def close(self) -> None: ...


def create_mcp_client(config: McpServerConfig) -> McpClient:
    transport = str(config.transport or "stdio").lower()
    if transport == "stdio":
        from .mcp_stdio import McpStdioClient

        return McpStdioClient(config)
    if transport in {"streamable_http", "http"}:
        from .mcp_http import McpStreamableHttpClient

        return McpStreamableHttpClient(config)
    raise ValueError(f"unsupported MCP transport: {config.transport}")


def build_mcp_tools(agent):
    tools = {}
    clients = getattr(agent, "mcp_clients", {})
    for server_name, client in clients.items():
        for spec in client.list_tools():
            tool_name = str(spec.get("name", "")).strip()
            if not tool_name:
                continue
            name = f"mcp__{server_name}__{tool_name}"
            tools[name] = RegisteredTool(
                name=name,
                schema=dict(spec.get("inputSchema", {}) or {}),
                description=str(spec.get("description", "MCP tool")),
                risky=True,
                runner=lambda args, client=client, tool_name=tool_name: _call(client, tool_name, args),
            )
    return tools


def _call(client: McpClient, tool_name: str, args: dict) -> ToolResult:
    result = client.call_tool(tool_name, args)
    content = result.get("content", [])
    text = "\n".join(str(item.get("text", "")) for item in content if isinstance(item, dict))
    return ToolResult(text or str(result), is_error=bool(result.get("isError")))
