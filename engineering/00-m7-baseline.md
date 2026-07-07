# M7 基线

- 日期：2026-08-12
- 起始提交：`de1e70b feat: add auditable business delivery loop`
- MCP 传输：仅 stdio；协议版本 `2025-06-18`；客户端实现位于 `pico/tools/mcp.py`。

## 既有能力

- stdio 子进程启动、initialize、tools/list、tools/call 和关闭；
- MCP 工具动态注册为 Moka Tool Registry 工具；
- 统一参数校验、权限检查和 Trace；
- 本地发布策略 MCP 的真实模型 Dogfood。

## 已知边界

- 不支持 Streamable HTTP、SSE、HTTP session 或网络错误分类；
- 外部服务凭据与响应大小没有远程传输层策略；
- stdio 调用在结果未知时也不存在网络重放问题。
