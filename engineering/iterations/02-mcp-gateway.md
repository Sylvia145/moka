# 02：Policy-aware MCP 工具网关

## 工程问题

外部 MCP 工具若绕过内部 ToolSpec、权限和证据链路，会使 Agent 的安全与可观测性失效。第一版需要以最小 stdio 协议接入，验证动态发现与统一治理能共存。

## 最小范围

- stdio server 配置、初始化、`tools/list` 与 `tools/call`；
- MCP schema 适配为内部注册工具，名称使用 server namespace；
- 复用既有参数校验、permission、tool policy、重复调用防护和 artifact 处理；
- mock server 覆盖确定性测试，并保留一个真实演示场景；
- 处理启动、协议、参数、超时和 server 退出错误。

## 非目标

不支持 HTTP/SSE、A2A、工具市场、复杂工具检索或高可用 server 管理。

## 选型

第一版采用内部轻量 stdio JSON-RPC client，而不引入快速演进的 MCP SDK 依赖。官方 stdio transport 要求 host 启动 server 子进程、以 UTF-8 换行分隔 JSON-RPC 消息，并完成 `initialize`、`notifications/initialized`、`tools/list` 与 `tools/call` 生命周期；这些正好覆盖本项目的最小范围。客户端只暴露工具能力，不声明 sampling、resources、prompts 或 tasks 能力。

工具注册将发生在 `Pico.build_tools()` 的既有注册表边界：MCP 工具被包装为 `RegisteredTool`，再由原有 `run_tool()` 完成参数校验、审批、tool policy、重复调用防护、artifact 和 trace。不会在模型循环中直接调用 MCP server。

## 实际问题

首次实现中，初始化复用请求方法但外层使用不可重入锁，导致同线程锁重入死锁。详见 [INC-0002](../incidents/INC-0002-mcp-initialize-reentrant-lock.md)。
