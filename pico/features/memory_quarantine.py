"""Pico 运行时实现模块。"""

import re

from .memory_lint import SECRET_PATTERNS

QUARANTINE_PATTERN = re.compile(
    r"ignore (?:previous|prior) instructions|</?(?:system|assistant)>|disregard all earlier|new instructions:|you are now",
    re.I,
)


def should_quarantine(note_text):
    """执行 `should_quarantine` 的内部逻辑。"""
    text = str(note_text)
    return bool(QUARANTINE_PATTERN.search(text)) or any(pattern.search(text) for pattern in SECRET_PATTERNS)
