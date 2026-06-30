# 基线记录

## 目标

建立后续迭代可比较的最小基线，只解决会阻塞评测、MCP 或 worker 开发的问题。

## 固定记录项

- 起始 commit、操作系统、Python 与依赖版本。
- 相关 focused tests 和完整测试的结果。
- 当前已知失败及其是否影响本轮范围。
- 代表任务集、执行命令、provider/model 标识与重复次数。
- 初始任务成功、工具轨迹、token 和时延数据。

## 当前已知限制

项目指南记录：Windows 下完整测试存在 Bash 路径和验证命令相关存量失败，且 Ruff 有历史存量问题。本阶段会以重新执行结果为准，避免将历史问题归因给后续改动。

## 实际发现

- `uv run` 首先受用户级 cache 权限和已被占用的 `moka.exe` 影响；基线测试改为直接使用现有 `.venv` 的 Python。
- `BenchmarkEvaluator` 在当前 Windows 环境因缺少 IANA 时区数据无法生成 artifact。详见 [INC-0001](incidents/INC-0001-windows-zoneinfo-benchmark-block.md)。
- `test_tool_policy_acceptance.py` 还存在 Windows 路径分隔符和 Unix shell 工具（`head`/`tail`）假设失败，当前记录为存量跨平台问题；它不阻塞评测器本身，后续按相关性处理。
- `test_safety_invariants.py` 在 Windows 当前权限下无法创建 symlink，且部分测试清空环境变量后 `Path.home()` 无法解析；这些是现有平台假设，未纳入本轮最小基线修复。

## 确定性评测结果

- 起始 commit：`ee15d236ded287ece414e290c9ab4591c7c3aae5`
- 环境：Windows、Python 3.12.4、现有 `.venv`
- 命令：`& .\.venv\Scripts\python.exe -c "... run_harness_regression_v2(...)"`
- artifact：`artifacts/engineering/baseline-harness.json`（本地忽略）
- 数据集：`benchmarks/coding_tasks.json`，12 个固定任务
- 模型：`ScriptedModelClient` / `scripted-deterministic`
- 结果：12/12 通过，任务成功率 1.0，预算内完成率 1.0，verifier 通过率 1.0
- 复现合同：`temperature=0.0`、`top_p=1.0`、`max_new_tokens=64`、`Asia/Shanghai`、`C.UTF-8`

## 基线验收

`tests/test_evaluator.py` 在修复后为 10 passed，且不再出现 Windows 子进程解码告警。完整项目测试和安全/工具策略测试仍有上述跨平台存量限制，本轮不将其伪装为已解决。
