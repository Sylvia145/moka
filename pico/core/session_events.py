"""Pico 运行时实现模块。

The run trace is per-task and diagnostic. The session event bus is the durable,
coarse-grained timeline for the interactive session itself.
"""

import json
from pathlib import Path

from .workspace import now


class SessionEventBus:
    def __init__(self, session_id, path, redact=None):
        """初始化对象状态。"""
        self.session_id = str(session_id)
        self.path = Path(path)
        self.redact = redact or (lambda value: value)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def emit(self, event, payload=None):
        """执行 `emit` 的内部逻辑。"""
        record = dict(payload or {})
        record["event"] = str(event)
        record["session_id"] = self.session_id
        record["created_at"] = now()
        record = self.redact(record)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(record, sort_keys=True) + "\n")
        return record
