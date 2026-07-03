# 05：统一端到端演示

## 场景

“应用外部发布规则，并由隔离 worker 写入 release note”。主 Agent 先通过本地 stdio MCP 获取规则，再派发带 `notes` write scope 的 worker；worker 在 detached Git worktree 写入文件，主工作区保持不变。

## 入口

```powershell
& .\.venv\Scripts\python.exe scripts\run_agent_runtime_demo.py --output artifacts\engineering\runtime-demo.json
```

## 验收证据

- `tests/test_runtime_demo.py`：1 passed（2026-08-11，3.10s）。
- 正式脚本运行：`status=passed`。
- trace 记录 `mcp__policy__get_release_rule` 和 worker 调度调用。
- worker 状态为 `completed`，结构化结果记录 `notes/release.md`。
- 文件仅存在于 worker worktree，主工作区不存在该路径。

## 边界

演示默认使用 `ScriptedModelClient`，用于可重复的集成演示，不作为真实模型能力指标。真实模型评测仍遵循 [04](04-live-evaluation.md) 的独立实验口径。
