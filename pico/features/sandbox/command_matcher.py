"""Pico 运行时实现模块。"""

from fnmatch import fnmatch


def command_is_excluded(command, patterns):
    """执行 `command_is_excluded` 的内部逻辑。"""
    command = str(command or "").strip()
    return any(fnmatch(command, str(pattern)) for pattern in patterns or ())
