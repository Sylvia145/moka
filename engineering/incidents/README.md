# Incident 记录规则

仅记录改变设计、导致指标失真、涉及权限/状态一致性、需要回滚或具有稳定复现路径的真实问题。

每个 Incident 包含：现象、复现、影响、已尝试方案、根因、修复、回归测试、证据和残留限制。普通语法或格式问题仅写入对应迭代文档。
# 事件索引

- [INC-0001：Windows 时区与基准阻塞](INC-0001-windows-zoneinfo-benchmark-block.md)
- [INC-0002：MCP initialize 可重入锁死](INC-0002-mcp-initialize-reentrant-lock.md)
- [INC-0003：worker 结果状态读取顺序](INC-0003-worker-result-state-order.md)
- [INC-0004：真实提供商冒烟评测认证失败](INC-0004-live-provider-auth-block.md)
- [INC-0005：Worker Manager 超出模块复杂度预算](INC-0005-worker-manager-entropy-budget.md)
- [INC-0006：发布治理 verifier 将 Markdown 格式误判为业务失败](INC-0006-release-verifier-markdown-format.md)
- [INC-0007：Dogfood 外部 pytest 受 Windows `uv` 编码影响失败](INC-0007-dogfood-uv-windows-decode.md)
- [INC-0008：隔离工作区缺少 pytest 依赖](INC-0008-isolated-workspace-test-dependency.md)
- [INC-0009：测试 verifier 与 pytest 文本耦合](INC-0009-test-verifier-framework-coupling.md)
