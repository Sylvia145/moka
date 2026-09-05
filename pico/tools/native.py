"""Pico 运行时实现模块。

把 agent 的工具注册表翻译成 provider 原生 function-calling 的声明（tools）。

为什么存在：
模型输出协议分两条轨道——文本协议（`<tool>`/`<final>` 标签，兼容任何只会吐字的
后端）与原生 function calling（请求带 `tools` 声明、后端返回结构化 `tool_calls`）。
这条翻译层只服务后者：把 `agent.available_tools()` 里每个工具的描述与参数约束
变成 OpenAI Responses / Anthropic / Chat Completions 三种协议都认识的
`{name, description, parameters}` 结构。

参数声明有三个来源，按优先级取：
1. 内置工具：`tools/schemas.py` 的 Pydantic 校验模型，`model_json_schema()`
   直接产出标准 JSON Schema（必填/可选/默认由字段类型与 Optional 推导，最准确）；
2. MCP 工具：其 `inputSchema` 本身就是 JSON Schema（`type: object` + `properties`
   + `required`），原样透传；
3. 通用 compact 描述（`{"path": "str", "start": "int=1"}`）：按字段类型推导 JSON
   Schema，作为 Pydantic 未覆盖工具的最后兜底。
"""

from __future__ import annotations

from .registry import _TOOL_SCHEMAS

_JSON_TYPE_MAP = {
    "str": "string",
    "int": "integer",
    "float": "number",
    "bool": "boolean",
}


def _split_field_spec(spec):
    """把 compact 字段描述拆成 (类型串, 是否可选)。"""
    spec = str(spec).strip()
    optional = spec.endswith("?")
    if optional:
        spec = spec[:-1]
    if "=" in spec:
        optional = True
        spec = spec.split("=", 1)[0]
    return spec.strip(), optional


def field_to_json_schema(field_name, spec):
    """把单个 compact 字段（如 `start` + `int=1`）转成一个 JSON Schema property。"""
    type_text, _ = _split_field_spec(spec)
    type_text = type_text.strip()
    if type_text.startswith("list[") and type_text.endswith("]"):
        item_type = type_text[len("list[") : -1].strip()
        return {
            "type": "array",
            "items": {"type": _JSON_TYPE_MAP.get(item_type, "string")},
        }
    return {"type": _JSON_TYPE_MAP.get(type_text, "string")}


def compact_schema_to_json(fields):
    """把 `{"path": "str", "start": "int=1"}` 风格的 compact schema 转成 JSON Schema。

    返回值形如 `{"type": "object", "properties": {...}, "required": [...]}`，
    与 Pydantic `model_json_schema()` 的输出对齐，方便调用方统一处理。
    """
    properties = {}
    required = []
    for field_name, spec in (fields or {}).items():
        field_name = str(field_name)
        properties[field_name] = field_to_json_schema(field_name, spec)
        _, optional = _split_field_spec(spec)
        if not optional:
            required.append(field_name)
    return {"type": "object", "properties": properties, "required": required}


def _looks_like_json_schema(schema):
    """判断一个 schema dict 是 JSON Schema（`type`+`properties`）而非 compact 描述。"""
    schema = dict(schema or {})
    return "properties" in schema or schema.get("type") == "object"


def parameters_for(name, schema):
    """为一个工具名解析它的 JSON Schema parameters。

    - 内置工具（name 在 Pydantic 校验表里）：直接用模型的 `model_json_schema()`；
    - 其余工具：schema 已是 JSON Schema 就原样使用，否则走 compact 推导。
    """
    model_cls = _TOOL_SCHEMAS.get(name)
    if model_cls is not None:
        return model_cls.model_json_schema()
    if _looks_like_json_schema(schema):
        return dict(schema)
    return compact_schema_to_json(schema)


def function_definition(name, tool):
    """把单个 RegisteredTool 转成 provider 无关的 function 定义。"""
    description = str(getattr(tool, "description", "") or "").strip()
    if getattr(tool, "risky", False):
        description = f"{description} (requires approval)" if description else "(requires approval)"
    return {
        "name": name,
        "description": description,
        "parameters": parameters_for(name, getattr(tool, "schema", {}) or {}),
    }


def build_tool_definitions(agent):
    """返回 `agent` 当前可见工具的原生 function 声明列表。

    与 `Pico.build_prefix()` 的可见工具集保持一致（都来自
    `available_tools()`），确保原生声明和文本协议里描述的是同一组动作。
    """
    return [
        function_definition(name, tool)
        for name, tool in sorted(agent.available_tools().items())
    ]
