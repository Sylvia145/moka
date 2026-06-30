# INC-0001：Windows 缺失 IANA 时区数据阻断 benchmark

## 现象

在 Windows / Python 3.12 环境运行 `tests/test_evaluator.py` 时，`BenchmarkEvaluator.run()` 在写入 `captured_at` 前失败，报错为 `ZoneInfoNotFoundError: Asia/Shanghai`。

## 复现

```powershell
& .\.venv\Scripts\python.exe -m pytest tests/test_evaluator.py -xvv
```

## 影响

固定 benchmark 无法生成 artifact，轨迹评测迭代没有可信基线。

## 根因

评测器直接依赖 `ZoneInfo("Asia/Shanghai")`。当前 Windows Python 的 `TZPATH` 为空，环境也未安装 `tzdata`；项目依赖中没有声明该包。

继续执行 benchmark 后还发现 verifier 固定以 `python3` 启动；Windows 环境没有该命令，因此 12 个任务均在 verifier 阶段失败。修复后，artifact 又因直接记录宿主 `LC_CTYPE` 而在 Windows 产生 `Chinese (Simplified)_China.936`、在 Unix 产生 `C.UTF-8`，使相同 benchmark 的元数据不可比较。三个问题都说明 benchmark 的执行环境假设没有被封装在 evaluator 中。完整评测测试还出现 Git 元数据子进程按系统 GBK 解码 UTF-8 输出的后台线程告警；虽然未使断言失败，但会使运行证据不可靠。

## 选型

| 方案 | 结论 |
| --- | --- |
| 新增 `tzdata` 运行时依赖 | 可行，但为生成时间戳增加环境相关依赖。 |
| 改用 UTC | 会改变现有 artifact 的时区合同。 |
| 对默认上海时区使用固定 UTC+08:00 回退 | 采用；保持既有时区名称和输出偏移，且不增加依赖。 |

## 修复

默认时区解析失败时，评测器使用带 `Asia/Shanghai` 名称的固定 UTC+08:00 timezone；其他无效时区仍抛出异常。verifier 在 Windows 下将前缀 `python3` 解析为当前解释器路径，artifact 同时保留声明命令和实际执行命令。artifact 的 locale 字段改为 fixture/verifier 明确采用的 `C.UTF-8` 合同，而不是宿主机 locale。shell、verifier 和 Git 元数据子进程捕获输出时显式以 UTF-8 解码并使用 `errors="replace"`，确保异常字节不会使后台读取线程崩溃。新增测试覆盖兼容路径。

## 回归验证

- `tests/test_evaluator.py` 应在无 IANA zoneinfo 数据、且没有 `python3` 命令的 Windows 环境通过。

## 残留限制

该回退仅服务当前 benchmark 的上海时区时间戳，不是任意 IANA 时区的通用替代实现。
