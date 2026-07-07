# INC-0007：Dogfood 外部 pytest 受 Windows `uv` 编码影响失败

- 日期：2026-08-12
- 严重度：阻塞订单修复真实场景的独立 verifier
- 影响：模型已修复代码并在自身工具链中报告测试通过，但 dogfood runner 的第二次 pytest 验证失败。

## 现象

首次 DeepSeek `order_pricing_bugfix` 运行中，`pricing_fixed` 与模型内 `pytest_ran` 均通过，外部 `uv run --with pytest ...` 验证失败，同时后台读取线程以 GBK 解码 UTF-8 输出时报错。

## 根因

dogfood runner 依赖全局 `uv`，且未固定子进程输出编码；Windows 上既受安装/缓存环境影响，也可能以 GBK 解码 pytest 输出。

## 修复

runner 改用执行自身的 `sys.executable -m pytest -q`，并显式 `encoding="utf-8"`、`errors="replace"`。这保证 fixture 使用项目已验证的虚拟环境，不依赖全局 `uv` 状态。

## 回归策略

保留 run1 的失败 artifact；修改后重跑同一 DeepSeek 场景，只有独立 pytest 通过才记为业务成功。
