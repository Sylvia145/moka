# 最终验证记录

## 本轮专项回归

2026-08-11：

```powershell
& .\.venv\Scripts\python.exe -m pytest tests\test_evaluator.py tests\test_mcp_tools.py tests\test_agent_workers_acceptance.py tests\test_runtime_demo.py -q
```

结果：27 passed，71.67s（在 worker 模块拆分前）；拆分后补充执行：

```powershell
& .\.venv\Scripts\python.exe -m pytest tests\test_architecture_boundaries.py tests\test_agent_workers_acceptance.py tests\test_runtime_demo.py tests\test_mcp_tools.py -q
```

结果：17 passed，27.91s。两组共同覆盖评测、MCP、worker 生命周期、并发队列、worktree 隔离、统一演示和架构预算。

Worker 模块拆分完成后的当前版本最终组合回归：

```powershell
& .\.venv\Scripts\python.exe -m pytest tests\test_evaluator.py tests\test_mcp_tools.py tests\test_agent_workers_acceptance.py tests\test_runtime_demo.py tests\test_architecture_boundaries.py -q
```

结果：28 passed，99.99s。

## 静态检查

新增或改动的 worker 拆分、工具注册表、演示脚本及其测试均通过专项 Ruff；`git diff --check` 通过。

## 全量 pytest

- 测试收集：528 项。
- `pytest tests -x`：25 passed 后首个失败为 `tests/test_benchmark_integrations.py::test_bench_script_env_max_steps_overrides_yaml_arg`。
- 原因：Windows 下 Bash 基准脚本调用 fake `uv` 时发生访问拒绝；该脚本不属于本轮改动范围。
- `pytest tests -q`：运行至约 68% 后仍存在多个失败，并在 600 秒外层时限超时；不宣称全量测试通过。

## 真实模型评测

GPT、Claude、DeepSeek 的单题冒烟均收到 HTTP 401。真实 36 次评测未启动，任何确定性结果均不替代真实模型能力数字。详见 [04](iterations/04-live-evaluation.md) 与 [INC-0004](incidents/INC-0004-live-provider-auth-block.md)。
