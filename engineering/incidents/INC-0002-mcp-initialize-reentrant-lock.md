# INC-0002：MCP 初始化请求造成同线程锁重入死锁

## 现象

首次通过 registry 动态发现 MCP 工具时测试无输出并持续等待。

## 根因

`_request()` 持有普通 `threading.Lock` 后调用 `_start()`；`_start()` 复用 `_request(..., initialize=False)` 发送 `initialize`，同一线程再次获取同一把不可重入锁而永久等待。

## 解决

将会话锁改为 `threading.RLock`。MCP 初始化、`tools/list` 和 `tools/call` 仍串行化，但生命周期内部可以复用同一 JSON-RPC 请求实现。

## 回归

`tests/test_mcp_tools.py` 覆盖初始化、动态发现、工具调用和关闭流程。
