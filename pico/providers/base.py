"""Pico 运行时实现模块。"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ModelResult:
    text: str
    metadata: dict = field(default_factory=dict)


def complete_model(model_client, prompt, max_new_tokens, **kwargs):
    """执行 `complete_model` 的内部逻辑。"""
    if hasattr(model_client, "complete_result"):
        return model_client.complete_result(prompt, max_new_tokens, **kwargs)
    text = model_client.complete(prompt, max_new_tokens, **kwargs)
    metadata = dict(getattr(model_client, "last_completion_metadata", {}) or {})
    return ModelResult(text=str(text), metadata=metadata)
