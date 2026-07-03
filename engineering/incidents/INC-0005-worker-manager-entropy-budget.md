# INC-0005：Worker Manager 超出模块复杂度预算

- 日期：2026-08-11
- 严重度：阻塞架构边界测试
- 影响：`tests/test_architecture_boundaries.py` 失败，无法证明 worker 模块保持可维护边界

## 现象

加入 timeout、并发队列和 Git worktree 后，`pico/core/worker_manager.py` 达到 319 行，超过项目规定的 220 行上限。

## 原因

会话状态管理、后台调度、超时监控和 worktree 生命周期被放入同一个管理器，职责边界被打破。

## 处理

将后台调度、并发计数、协作式取消和 worktree 创建拆分到 `pico/core/worker_background.py`；`WorkerManager` 只保留会话状态、任务 API 和通知读取。拆分后 manager 为 204 行，架构边界测试通过。

## 验证

`tests/test_architecture_boundaries.py`、`tests/test_agent_workers_acceptance.py`、`tests/test_mcp_tools.py`、`tests/test_runtime_demo.py` 共 17 项通过。
