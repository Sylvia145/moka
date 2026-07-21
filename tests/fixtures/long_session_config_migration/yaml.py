"""Pico 自动化测试模块。"""
def safe_load(handle):
    """执行 `safe_load` 的内部逻辑。"""
    data = {}
    for line in handle:
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        value = value.strip()
        if value.isdigit():
            value = int(value)
        data[key.strip()] = value
    return data
