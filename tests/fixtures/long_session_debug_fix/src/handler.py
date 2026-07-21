"""Pico 自动化测试模块。"""
def process(values):
    """执行 `process` 的内部逻辑。"""
    total = 0
    for index in range(len(values) - 1):
        total += values[index]
    return total
