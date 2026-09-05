"""原生 function-calling 双轨的引擎集成测试。

`test_native_schema.py` 已覆盖 schema 转换与 `parse_native` 解码的单测；
这里覆盖引擎层的行为：带 `supports_tool_calls` 的客户端走原生轨（声明 tools、
解码结构化 tool_calls、无标签纯文本即 final），后端拒绝 tools 参数时自动降级回
文本协议并重发本 attempt，以及三种 provider 返回形状的解码。

文本协议路径（ScriptedModelClient 无 supports_tool_calls）由既有引擎测试覆盖，
这里不再重复。
"""

import json

from pico import Pico, SessionStore, WorkspaceContext
from pico.providers import ProviderError
from pico.providers.base import ModelResult
from pico.providers.clients import (
    _extract_anthropic_tool_calls,
    _extract_chat_tool_calls,
    _extract_responses_tool_calls,
)


class NativeScriptedModelClient:
    """声明支持原生 tools 的脚本客户端。

    `results` 里依次放 `ModelResult`（原样返回）或 `BaseException`（抛出）。
    记录每次请求收到的 `prompt` 与 `tools` 参数，供断言双轨接线是否正确。
    """

    def __init__(self, results):
        self.results = list(results)
        self.supports_tool_calls = True
        self.supports_prompt_cache = False
        self.last_completion_metadata = {}
        self.prompts = []
        self.seen_tools = []

    def complete_result(
        self,
        prompt,
        max_new_tokens,
        *,
        tools=None,
        prompt_cache_key=None,
        prompt_cache_retention=None,
    ):
        self.prompts.append(prompt)
        self.seen_tools.append(tools)
        if not self.results:
            raise RuntimeError("scripted model ran out of outputs")
        item = self.results.pop(0)
        if isinstance(item, BaseException):
            raise item
        if isinstance(item, str):
            # 裸字符串按文本协议输出处理（降级后断言文本轨仍走 agent.parse）。
            item = ModelResult(text=item, metadata={})
        return item


def build_agent(tmp_path, client, **kwargs):
    """执行 `build_agent` 的内部逻辑。"""
    (tmp_path / "README.md").write_text("demo\n", encoding="utf-8")
    workspace = WorkspaceContext.build(tmp_path)
    store = SessionStore(tmp_path / ".pico" / "sessions")
    return Pico(
        model_client=client,
        workspace=workspace,
        session_store=store,
        approval_policy="auto",
        **kwargs,
    )


def _tool_call(name, args):
    """构造一次带 id 的原生 tool call（贴近真实后端归一化结果）。"""
    return {"id": f"call_{name}", "name": name, "args": args}


def test_native_engine_declares_tools_and_executes_tool_then_final(tmp_path):
    """原生轨全流程：tools 声明 → 结构化调用 → 真实执行 → 纯文本 final。"""
    client = NativeScriptedModelClient(
        [
            ModelResult(
                text="",
                metadata={},
                tool_calls=[_tool_call("write_file", {"path": "notes/native.txt", "content": "n\n"})],
            ),
            ModelResult(text="Wrote natively.", metadata={}),
        ]
    )
    agent = build_agent(tmp_path, client)

    events = list(agent.engine.run_turn("write the native note"))

    # 与文本协议会话同构：tool→result→再请求→final。
    assert [event["type"] for event in events] == [
        "turn_started",
        "model_requested",
        "model_parsed",
        "tool_call",
        "tool_result",
        "model_requested",
        "model_parsed",
        "final",
        "turn_finished",
    ]
    assert events[-2]["content"] == "Wrote natively."
    assert (tmp_path / "notes" / "native.txt").read_text(encoding="utf-8") == "n\n"

    # 两次请求都应带上原生 tools 声明，且声明是 {name,description,parameters}。
    assert len(client.seen_tools) == 2
    for definitions in client.seen_tools:
        assert definitions and all(
            {"name", "description", "parameters"} <= set(definition)
            for definition in definitions
        )
    write_file = next(d for d in client.seen_tools[0] if d["name"] == "write_file")
    assert write_file["parameters"]["type"] == "object"
    assert "path" in write_file["parameters"]["required"]

    # 原生前缀：没有 <tool>/<final> 的 XML 协议说明，也不用写 final 标签。
    for prompt in client.prompts:
        assert "Return one or more <tool>" not in prompt
        assert "Valid response examples" not in prompt
        assert "<final>your answer</final>" not in prompt
    # 但工具列表仍在手册里。
    assert "list_files(" in client.prompts[0]


def test_native_engine_plain_text_is_final_without_tag(tmp_path):
    """原生轨：模型不回调用、直接给一段无标签纯文本，就是最终回答。"""
    client = NativeScriptedModelClient(
        [ModelResult(text="无需工具，直接回答。", metadata={})]
    )
    agent = build_agent(tmp_path, client)

    events = list(agent.engine.run_turn("just answer me"))

    finals = [event for event in events if event["type"] == "final"]
    assert finals and finals[0]["content"] == "无需工具，直接回答。"


def test_native_engine_downgrades_when_provider_rejects_tools(tmp_path):
    """后端 400 拒绝 tools 参数 → 降级文本协议并重发，本 attempt 不被吞掉。"""
    rejection = ProviderError(
        "Unknown parameter: 'tools'.",
        provider="openai",
        code="invalid_request_error",
        http_status=400,
        body_excerpt="Unknown parameter: 'tools' is not supported",
    )
    client = NativeScriptedModelClient(
        [
            rejection,
            '<tool name="write_file" path="notes/after.txt"><content>after\n</content></tool>',
            "<final>Done after downgrade.</final>",
        ]
    )
    agent = build_agent(tmp_path, client)

    events = list(agent.engine.run_turn("write it, and downgrade gracefully"))

    assert agent._tools_disabled is True
    finals = [event for event in events if event["type"] == "final"]
    assert finals and finals[0]["content"] == "Done after downgrade."
    assert (tmp_path / "notes" / "after.txt").read_text(encoding="utf-8") == "after\n"

    # 第一次请求声明了 tools，降级后不再声明。
    assert client.seen_tools[0] is not None
    assert client.seen_tools[1] is None
    assert client.seen_tools[2] is None
    # 前缀同步切换：第一次原生手册，之后恢复 <tool>/<final> 文本协议说明。
    assert "Return one or more <tool>" not in client.prompts[0]
    for prompt in client.prompts[1:]:
        assert "Return one or more <tool>" in prompt


def test_native_engine_records_downgrade_transition(tmp_path):
    """降级会在 transition 证据里留下 native_tools_unavailable 一次。"""
    rejection = ProviderError(
        "tools not accepted",
        provider="anthropic",
        code="invalid_request_error",
        http_status=400,
        body_excerpt="extra fields not permitted: 'tools'",
    )
    client = NativeScriptedModelClient(
        [rejection, "<final>Degraded.</final>"]
    )
    agent = build_agent(tmp_path, client)

    list(agent.engine.run_turn("degrade"))

    report = json.loads(
        (agent.current_run_dir / "report.json").read_text(encoding="utf-8")
    )
    summary = report["evidence_summaries"]["transition_summary"]
    assert summary["reasons"].get("native_tools_unavailable") == 1


# ---- 三种 provider 返回形状的解码（纯函数，不碰网络） ----


def test_decode_openai_responses_function_call():
    data = {
        "output": [
            {"type": "function_call", "id": "fc_1", "name": "read_file",
             "arguments": '{"path": "README.md"}'}
        ]
    }
    calls = _extract_responses_tool_calls(data)
    assert calls == [{"id": "fc_1", "name": "read_file", "args": {"path": "README.md"}}]


def test_decode_chat_completions_tool_calls():
    data = {
        "choices": [
            {
                "message": {
                    "tool_calls": [
                        {"id": "call_a", "type": "function",
                         "function": {"name": "list_files", "arguments": "{}"}}
                    ]
                }
            }
        ]
    }
    calls = _extract_chat_tool_calls(data)
    assert calls == [{"id": "call_a", "name": "list_files", "args": {}}]


def test_decode_anthropic_tool_use_dict_input():
    data = {
        "content": [
            {"type": "tool_use", "id": "toolu_1", "name": "run_shell",
             "input": {"command": "pwd", "timeout": 10}}
        ]
    }
    calls = _extract_anthropic_tool_calls(data)
    assert calls == [
        {"id": "toolu_1", "name": "run_shell", "args": {"command": "pwd", "timeout": 10}}
    ]


def test_decode_ignores_blocks_without_tool_role():
    data = {
        "content": [
            {"type": "text", "text": "hello"},
            {"type": "tool_use", "id": "toolu_2", "name": "search", "input": {}},
        ]
    }
    calls = _extract_anthropic_tool_calls(data)
    assert len(calls) == 1 and calls[0]["name"] == "search"
