"""Pico 运行时实现模块。"""

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class ToolResult:
    content: str
    is_error: bool = False


@dataclass(frozen=True)
class RegisteredTool:
    name: str
    schema: dict
    description: str
    risky: bool
    runner: Callable[[dict], str]

    @property
    def read_only(self):
        """执行 `read_only` 的内部逻辑。"""
        return not self.risky

    def execute(self, args):
        """执行 `execute` 的内部逻辑。"""
        result = self.runner(args)
        if isinstance(result, ToolResult):
            return result
        return ToolResult(content=str(result))

    def __getitem__(self, key):
        """执行 `__getitem__` 的内部逻辑。"""
        if key == "run":
            return self.runner
        return getattr(self, key)
