# INC-0003：Worker 结果证据读取早于 child task state 初始化

## 现象

为 worker 增加结构化结果后，后台线程抛出 `UnboundLocalError`，主 Agent 未收到 worker 完成通知并提前结束。

## 根因

`collect_worker_artifacts()` 需要 child runtime 的 `current_task_state`，但调用被置于 `task.runtime.ask()` 和 `task_state` 获取之前。

## 解决

将 evidence 提取移动到 child 运行结束、读取 `current_task_state` 之后；结果合同因此只包含已完成 run 的真实 changed paths、verification 和 error codes。

## 回归

现有 worker acceptance suite 覆盖后台通知、续接、写入范围和 timeout 路径。
