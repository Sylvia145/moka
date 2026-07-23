"""Shell 命令的跨平台兼容处理。"""

import os
import re
import sys


def normalize_shell_command(command: object) -> str:
    """将常见的 Python 3 命令别名转换为当前解释器。"""
    command = str(command or "").strip()
    if os.name != "nt":
        return command
    if command.startswith("python3 "):
        command = f'"{sys.executable}" {command.removeprefix("python3 ")}'
    if _requires_powershell_pipe_compatibility(command):
        command = _translate_posix_output_filters(command)
        return f'powershell.exe -NoProfile -Command "& {{ {command} }}"'
    return command


def _requires_powershell_pipe_compatibility(command: str) -> bool:
    """仅为 cmd.exe 缺失的常用只读输出过滤器切换解释器。"""
    return bool(re.search(r"\b(?:head|tail|grep)\b", command))


def _translate_posix_output_filters(command: str) -> str:
    """将受支持的 POSIX 输出过滤器转换为等价 PowerShell 管道。"""
    command = command.replace("&&", ";")
    command = re.sub(r"\bhead\s+-(\d+)", r"Select-Object -First \1", command)
    command = re.sub(r"\btail\s+-(\d+)", r"Select-Object -Last \1", command)
    return re.sub(r"\bgrep\s+([^\s|;]+)", r"Select-String -Pattern \1", command)
