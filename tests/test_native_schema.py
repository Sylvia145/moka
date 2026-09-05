"""原生 function-calling schema 转换与解码的单测。

文本协议解析器 `model_output.parse` 的测试仍由既有的引擎/协议用例覆盖；
这里只覆盖新增的 `tools/native.py` 与 `model_output.parse_native` 双轨部分。
"""

from pico.core import model_output as mo
from pico.tools import native
from pico.tools.native import (
    compact_schema_to_json,
    field_to_json_schema,
    function_definition,
    parameters_for,
)


def test_compact_field_str_required():
    assert field_to_json_schema("path", "str") == {"type": "string"}


def test_compact_field_int_with_default_is_optional():
    schema, required = field_to_json_schema("start", "int=1"), None
    assert schema == {"type": "integer"}
    assert compact_schema_to_json({"path": "str", "start": "int=1"}) == {
        "type": "object",
        "properties": {"path": {"type": "string"}, "start": {"type": "integer"}},
        "required": ["path"],
    }


def test_compact_optional_marker():
    out = compact_schema_to_json({"path": "str?"})
    assert out["required"] == []
    assert out["properties"]["path"] == {"type": "string"}


def test_compact_list_type():
    assert field_to_json_schema("choices", "list[str]=[]") == {
        "type": "array",
        "items": {"type": "string"},
    }
    out = compact_schema_to_json({"choices": "list[str]=[]"})
    assert out["properties"]["choices"]["type"] == "array"


def test_json_schema_passthrough():
    schema = {"type": "object", "properties": {"a": {"type": "string"}}, "required": ["a"]}
    assert parameters_for("anything", schema) == schema


def test_internal_tool_uses_pydantic_json_schema():
    # read_file 有 Pydantic 校验模型，parameters 应含 start 默认值推导的必填规则。
    params = parameters_for("read_file", {"path": "str", "start": "int=1"})
    assert params["type"] == "object"
    assert "path" in params["properties"]
    assert "required" in params and "path" in params["required"]
    assert "start" not in params["required"]


def test_function_definition_carries_risky_flag():
    class _FakeTool:
        schema = {"path": "str"}
        description = "Read a file."
        risky = True

    definition = function_definition("read_file", _FakeTool())
    assert definition["name"] == "read_file"
    assert "(requires approval)" in definition["description"]


# ---- parse_native：把客户端结构化返回解码成 (kind, payload) ----


def test_parse_native_single_tool_call():
    kind, payload = mo.parse_native("", [{"name": "read_file", "args": {"path": "a.py"}}])
    assert kind == "tool"
    assert payload == {"name": "read_file", "args": {"path": "a.py"}}


def test_parse_native_multiple_tool_calls():
    calls = [
        {"name": "list_files", "args": {}},
        {"name": "read_file", "args": {"path": "a.py"}},
    ]
    kind, payload = mo.parse_native("", calls)
    assert kind == "tools"
    assert len(payload) == 2


def test_parse_native_string_arguments():
    kind, payload = mo.parse_native("", [{"name": "run_shell", "args": '{"command":"ls"}'}])
    assert kind == "tool"
    assert payload == {"name": "run_shell", "args": {"command": "ls"}}


def test_parse_native_plain_text_is_final():
    # 原生模式：无 <final> 包裹的纯文本就是最终回答。
    kind, payload = mo.parse_native("完成了。", None)
    assert kind == "final"
    assert payload == "完成了。"


def test_parse_native_empty_is_retry():
    kind, payload = mo.parse_native("", None)
    assert kind == "retry"


def test_parse_native_falls_back_to_text_protocol():
    # 原生模式下模型若仍吐 <tool> 标签，应复用文本解析而非当最终回答。
    kind, payload = mo.parse_native('<tool>{"name":"list_files","args":{}}</tool>', None)
    assert kind == "tool"
    assert payload == {"name": "list_files", "args": {}}


def test_build_tool_definitions_respects_available_tools():
    class _FakeAgent:
        def available_tools(self):
            return {
                "list_files": function_definition(
                    "list_files",
                    type("_T", (), {"schema": {"path": "str='.'"}, "description": "List.", "risky": False})(),
                ),
            }

    definitions = native.build_tool_definitions(_FakeAgent())
    assert [d["name"] for d in definitions] == ["list_files"]
    assert definitions[0]["parameters"]["type"] == "object"
