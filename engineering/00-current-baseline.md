# M6 当前基线

## 目的

在引入发布治理场景前冻结当前可靠 Agent Runtime 的状态，确保后续业务场景、真实模型实验和回归结果可比较。

## 环境与代码

- 日期：2026-08-12
- 基线提交：`2348397`
- 运行环境：Windows、Python 3.12、项目现有 `.venv`
- 模型配置：OpenAI、Anthropic、DeepSeek 三个 `.pico.toml` profile 均完成最小真实请求验证；密钥不记录。

## 现有能力

- trace 轨迹评测：固定 12 题、verifier、工具路径与预算合规。
- stdio MCP：动态发现、参数校验、权限与 trace 复用。
- worker：timeout、FIFO 并发队列、结构化结果和 Git worktree 隔离。
- 确定性统一演示：MCP 规则、worker 隔离写入和运行报告。

## 已知验证边界

- 当前代码版本专项组合回归为 28 passed；完整 pytest 在 Windows 仍含 Bash 基准脚本兼容性失败和慢场景，不作为全绿结论。
- 历史 12 题主要验证 runtime/评测器，不能单独证明真实业务交付能力。

## 本轮目标

新增一个可复现的 Billing API 发布治理场景：外部规则经 MCP 输入、worker 生成隔离的审查交付物、人工审批前不自动合并，并以真实模型实验验证。
