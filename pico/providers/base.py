"""Pico 运行时实现模块。"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ModelResult:
    text: str
    metadata: dict = field(default_factory=dict)
    tool_calls: list | None = None


def complete_model(model_client, prompt, max_new_tokens, **kwargs):
    """执行 `complete_model` 的内部逻辑。

    `tools`（可选）是原生 function-calling 声明。带 tools 时，支持该能力的客户端
    会返回带 `tool_calls` 的 `ModelResult`；不支持的后端/脚本客户端自动忽略该参数，
    走纯文本协议路径，由上层据此做双轨解码。
    """
    if hasattr(model_client, "complete_result"):
        return model_client.complete_result(prompt, max_new_tokens, **kwargs)
    text = model_client.complete(prompt, max_new_tokens, **kwargs)
    metadata = dict(getattr(model_client, "last_completion_metadata", {}) or {})
    return ModelResult(text=str(text), metadata=metadata)
