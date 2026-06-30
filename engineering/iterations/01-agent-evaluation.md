# 01：Agent 轨迹评测

## 工程问题

Agent 的最终回答正确，不代表工具选择、权限行为、步骤数和成本可靠。模型、prompt 或 runtime 变更后，需要使用固定任务和运行证据判断是否发生回归。

## 最小范围

- 固定 10--15 个代表任务及其结果 verifier、必需/禁止工具事件。
- 从真实 run trace 中计算结果、轨迹合规、工具步骤、token 和时延。
- 输出可比较的 JSON 与 Markdown 报告。
- 日常使用确定性测试；里程碑使用主模型进行分层重复实验。

## 预期风险

预期风险不等于实际 Incident。只有发生并影响设计、指标或可靠性时，才会单独记录根因和修复。

- report、trace 与 task state 的数据不一致；
- provider usage 字段缺失或口径不同；
- verifier 过松或过严；
- 模型失败和基础设施失败混淆；
- Windows 命令或路径影响实验可复现性。

## 实际实现与发现

- 在既有 `BenchmarkEvaluator` 中读取真实 `trace.jsonl`，为每个任务输出调用工具序列、缺失必需工具、禁止工具调用和轨迹合规结果，并在 artifact summary 中聚合合规率。
- 初版错误地将 `allowed_tools` 作为必需工具集合，导致只读恢复任务被误判。修正为仅由任务显式 `trajectory.required_tools` 约束；前七个修改类任务声明 `read_file`、`patch_file` 为必需工具，`run_shell` 为禁止工具。
- 直接重复使用固定 artifact workspace 时，Windows 的原子写入可能遇到文件占用；探针改为每次使用独立临时 workspace。该行为将在后续报告 runner 中保持。
