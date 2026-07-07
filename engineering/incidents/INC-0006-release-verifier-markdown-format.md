# INC-0006：发布治理 verifier 将 Markdown 格式误判为业务失败

- 日期：2026-08-12
- 严重度：阻塞真实业务 dogfood 通过率
- 影响：真实模型已完成规则读取、隔离报告写入和阻塞项识别，但场景被错误标记为失败。

## 现象

首次 DeepSeek 发布治理运行中，报告写入 `**POLICY:** billing-release-v1` 和 `**STATUS:** BLOCKED`。原 verifier 使用普通字符串 `POLICY: ...`、`STATUS: ...` 判断，未识别 Markdown 加粗后的同一语义。

## 根因

验收断言把报告表现格式当成业务语义，导致对等 Markdown 格式产生假阴性。

## 修复

验证前移除 Markdown 强调符号，再检查字段和值；仍要求固定的业务字段和值，不放宽为模糊关键词匹配。

## 回归

确定性发布治理测试覆盖普通字段格式；修复后将完整重跑真实 dogfood，保留 run1 失败 artifact 与重跑结果。
