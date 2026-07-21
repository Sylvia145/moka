"""Pico 运行时实现模块。"""

from .providers.base import ModelResult


class ScriptedModelClient:
    def __init__(self, outputs):
        """初始化对象状态。"""
        self.outputs = list(outputs)
        self.prompts = []
        self.supports_prompt_cache = False
        self.last_completion_metadata = {}

    def complete(self, prompt, max_new_tokens, **kwargs):
        """执行 `complete` 的内部逻辑。"""
        self.prompts.append(prompt)
        if not getattr(self, "last_completion_metadata", None):
            self.last_completion_metadata = {}
        if not self.outputs:
            raise RuntimeError("scripted model ran out of outputs")
        output = self.outputs.pop(0)
        if isinstance(output, BaseException):
            raise output
        return output

    def complete_result(self, prompt, max_new_tokens, **kwargs):
        """执行 `complete_result` 的内部逻辑。"""
        return ModelResult(
            text=self.complete(prompt, max_new_tokens, **kwargs),
            metadata=dict(self.last_completion_metadata),
        )
