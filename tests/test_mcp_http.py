"""Pico 自动化测试模块。"""
import pytest

from pico import Pico, SessionStore, WorkspaceContext
from pico.evaluation.mcp_http_fault_server import http_mcp_server
from pico.testing import ScriptedModelClient
from pico.tools import McpServerConfig
from pico.tools.mcp import create_mcp_client
from pico.tools.mcp_http import (
    McpHttpError,
    McpOutcomeUnknownError,
)


def _config(url, **kwargs):
    """执行 `_config` 的内部逻辑。"""
    return McpServerConfig("remote", transport="streamable_http", url=url, timeout=0.05, **kwargs)


def test_streamable_http_json_registers_tools_in_existing_registry(tmp_path):
    """执行 `test_streamable_http_json_registers_tools_in_existing_registry` 的内部逻辑。"""
    with http_mcp_server() as (state, url):
        workspace = WorkspaceContext.build(tmp_path)
        agent = Pico(
            model_client=ScriptedModelClient([]),
            workspace=workspace,
            session_store=SessionStore(tmp_path / ".pico" / "sessions"),
            approval_policy="auto",
            mcp_servers=(_config(url),),
        )

        assert "mcp__remote__echo" in agent.tools
        assert agent.run_tool("mcp__remote__echo", {"text": "hello"}) == "hello"
        assert state["calls"][0]["request"]["method"] == "initialize"
        assert state["calls"][1]["request"]["method"] == "notifications/initialized"
        assert state["calls"][2]["request"]["method"] == "tools/list"
        assert state["calls"][3]["headers"]["Mcp-Session-Id"] == "session-1"
        agent.mcp_clients["remote"].close()


def test_streamable_http_supports_sse_tool_discovery():
    """执行 `test_streamable_http_supports_sse_tool_discovery` 的内部逻辑。"""
    with http_mcp_server("sse") as (_state, url):
        client = create_mcp_client(_config(url))

        assert client.list_tools()[0]["name"] == "echo"
        client.close()


def test_streamable_http_recovers_expired_session_for_read_operation():
    """执行 `test_streamable_http_recovers_expired_session_for_read_operation` 的内部逻辑。"""
    with http_mcp_server(expire_first=True) as (state, url):
        client = create_mcp_client(_config(url, max_retries=1))

        assert client.list_tools()[0]["name"] == "echo"
        assert state["initialize_count"] == 2
        client.close()


@pytest.mark.parametrize(
    ("mode", "cause_code"),
    [
        ("timeout", "mcp_http_timeout"),
        ("disconnect", "mcp_http_connect_failed"),
        ("truncated", "mcp_invalid_response"),
        ("server_error", "mcp_http_server_error"),
    ],
)
def test_streamable_http_does_not_retry_side_effect_when_result_is_unknown(mode, cause_code):
    """结果未知的所有故障窗口均只允许一次可能有副作用的调用。"""
    with http_mcp_server(mode) as (state, url):
        client = create_mcp_client(_config(url, max_retries=3))

        with pytest.raises(McpOutcomeUnknownError, match="mcp_outcome_unknown") as error:
            client.call_tool("echo", {"text": "write once"})

        assert error.value.cause_code == cause_code
        assert state["tool_call_count"] == 1
        assert len(state["side_effects"]) == 1
        assert len({effect["request_id"] for effect in state["side_effects"]}) == 1
        client.close()


def test_streamable_http_retries_read_operation_after_transient_server_errors():
    """只读 tools/list 保留按配置重试的能力。"""
    with http_mcp_server(list_failures=2) as (state, url):
        client = create_mcp_client(_config(url, max_retries=3))

        assert client.list_tools()[0]["name"] == "echo"
        tool_list_calls = [call for call in state["calls"] if call["request"]["method"] == "tools/list"]
        assert len(tool_list_calls) == 3
        assert state["tool_call_count"] == 0
        client.close()


@pytest.mark.parametrize("mode", ["timeout", "disconnect", "truncated", "server_error"])
def test_streamable_http_outcome_unknown_is_preserved_in_agent_trace_metadata(tmp_path, mode):
    """结果未知必须进入 Agent 工具元数据，供 Trace 与指标消费。"""
    with http_mcp_server(mode) as (state, url):
        agent = Pico(
            model_client=ScriptedModelClient([]),
            workspace=WorkspaceContext.build(tmp_path),
            session_store=SessionStore(tmp_path / ".pico" / "sessions"),
            approval_policy="auto",
            mcp_servers=(_config(url),),
        )

        assert "mcp_outcome_unknown" in agent.run_tool("mcp__remote__echo", {"text": "write once"})
        assert agent._last_tool_result_metadata["tool_error_code"] == "mcp_outcome_unknown"
        assert state["tool_call_count"] == 1
        agent.mcp_clients["remote"].close()


def test_streamable_http_uses_environment_token_without_exposing_value(monkeypatch):
    """执行 `test_streamable_http_uses_environment_token_without_exposing_value` 的内部逻辑。"""
    token = "moka-test-token-not-for-artifacts"
    monkeypatch.setenv("MOKA_REMOTE_TOKEN", token)
    with http_mcp_server(require_token=token) as (state, url):
        client = create_mcp_client(_config(url, token_env="MOKA_REMOTE_TOKEN"))

        assert client.list_tools()[0]["name"] == "echo"
        assert state["calls"][0]["headers"]["Authorization"] == f"Bearer {token}"
        client.close()

    assert token not in str(client.config)
    monkeypatch.delenv("MOKA_REMOTE_TOKEN")


def test_streamable_http_limits_response_size():
    """执行 `test_streamable_http_limits_response_size` 的内部逻辑。"""
    with http_mcp_server("large") as (_state, url):
        # 256B 能容纳 initialize(约140B) 与 tools/list 正常响应(约197B)，仅 large 分支被拒。
        client = create_mcp_client(_config(url, max_response_bytes=256))

        with pytest.raises(McpHttpError, match="mcp_response_too_large"):
            client.list_tools()
        client.close()


def test_streamable_http_rejects_non_local_plain_http():
    """执行 `test_streamable_http_rejects_non_local_plain_http` 的内部逻辑。"""
    with pytest.raises(ValueError, match="requires HTTPS"):
        create_mcp_client(McpServerConfig("unsafe", transport="http", url="http://example.com/mcp"))


def test_streamable_http_does_not_expose_rejected_token(monkeypatch):
    """执行 `test_streamable_http_does_not_expose_rejected_token` 的内部逻辑。"""
    token = "moka-token-that-must-not-appear-in-errors"
    monkeypatch.setenv("MOKA_BAD_TOKEN", token)
    with http_mcp_server(require_token="different-token") as (_state, url):
        client = create_mcp_client(_config(url, token_env="MOKA_BAD_TOKEN"))

        with pytest.raises(McpHttpError, match="mcp_http_unauthorized") as error:
            client.list_tools()

    assert token not in str(error.value)
    monkeypatch.delenv("MOKA_BAD_TOKEN")


def test_streamable_http_idempotent_retry_dedups_side_effect_when_server_cooperates():
    """服务端按 Idempotency-Key 去重时，重试不产生第二次副作用。"""
    with http_mcp_server("disconnect", fail_first_call=True) as (state, url):
        client = create_mcp_client(_config(url, max_idempotent_retries=1))

        result = client.call_tool("echo", {"text": "write once"})
        assert result["content"][0]["text"] == "write once"
        assert state["tool_call_count"] == 2
        assert len(state["side_effects"]) == 1
        assert state["dedup_hits"] == 1
        assert client.last_idempotent_retries == 1
        client.close()


def test_streamable_http_idempotent_retry_is_opt_out_by_default():
    """默认配置不发送 Idempotency-Key，结果未知仍不重试。"""
    with http_mcp_server("disconnect") as (state, url):
        client = create_mcp_client(_config(url, max_retries=3))

        with pytest.raises(McpOutcomeUnknownError, match="mcp_outcome_unknown") as error:
            client.call_tool("echo", {"text": "write once"})

        assert error.value.cause_code == "mcp_http_connect_failed"
        assert state["tool_call_count"] == 1
        assert len(state["side_effects"]) == 1
        tools_call_headers = [
            call["headers"] for call in state["calls"] if call["request"]["method"] == "tools/call"
        ]
        assert all("Idempotency-Key" not in headers for headers in tools_call_headers)
        assert client.last_idempotent_retries == 0
        client.close()


def test_streamable_http_idempotent_key_is_stable_across_retries():
    """同一次逻辑调用的重试请求携带同一个 Idempotency-Key。"""
    with http_mcp_server("timeout", dedup_idempotent=False) as (state, url):
        client = create_mcp_client(_config(url, max_idempotent_retries=1))

        with pytest.raises(McpOutcomeUnknownError):
            client.call_tool("echo", {"text": "write once"})

        keys = [
            call["headers"].get("Idempotency-Key")
            for call in state["calls"] if call["request"]["method"] == "tools/call"
    ]
    assert len(keys) == 2
    assert keys[0] == keys[1]
    assert len(keys[0]) == 64
    client.close()


def test_streamable_http_idempotent_retry_still_raises_outcome_unknown_when_not_recovered():
    """重试后仍无法确认结果时，保留 mcp_outcome_unknown 与重试计数。"""
    with http_mcp_server("timeout", dedup_idempotent=False) as (state, url):
        client = create_mcp_client(_config(url, max_idempotent_retries=1))

        with pytest.raises(McpOutcomeUnknownError, match="mcp_outcome_unknown") as error:
            client.call_tool("echo", {"text": "write once"})

        assert error.value.cause_code == "mcp_http_timeout"
        assert state["tool_call_count"] == 2
        assert len(state["side_effects"]) == 2
        assert client.last_idempotent_retries == 1
        client.close()


def test_streamable_http_idempotent_retry_does_not_retry_unauthorized(monkeypatch):
    """授权拒绝属于确定性失败，不在幂等重试集合内。"""
    token = "wrong-token"
    monkeypatch.setenv("MOKA_WRONG_TOKEN", token)
    with http_mcp_server(require_token="good") as (state, url):
        client = create_mcp_client(_config(url, token_env="MOKA_WRONG_TOKEN", max_idempotent_retries=1))

        with pytest.raises(McpHttpError, match="mcp_http_unauthorized"):
            client.call_tool("echo", {"text": "write once"})

        assert state["tool_call_count"] == 0
        assert client.last_idempotent_retries == 0
        client.close()
    monkeypatch.delenv("MOKA_WRONG_TOKEN")


def test_streamable_http_idempotency_key_is_unique_per_logical_call():
    """相同参数的两次独立写操作携带不同幂等键，避免被服务端误去重。"""
    with http_mcp_server() as (state, url):
        client = create_mcp_client(_config(url, max_idempotent_retries=1))

        client.call_tool("echo", {"text": "write once"})
        client.call_tool("echo", {"text": "write once"})

        assert state["tool_call_count"] == 2
        assert len(state["side_effects"]) == 2
        assert len(state["idempotent_keys_seen"]) == 2
        assert state["idempotent_keys_seen"][0] != state["idempotent_keys_seen"][1]
        client.close()


def test_streamable_http_idempotent_retry_recorded_in_agent_trace_metadata(tmp_path):
    """成功路径在 Agent 工具元数据中记录幂等重试次数。"""
    with http_mcp_server("disconnect", fail_first_call=True) as (state, url):
        agent = Pico(
            model_client=ScriptedModelClient([]),
            workspace=WorkspaceContext.build(tmp_path),
            session_store=SessionStore(tmp_path / ".pico" / "sessions"),
            approval_policy="auto",
            mcp_servers=(_config(url, max_idempotent_retries=1),),
        )

        assert agent.run_tool("mcp__remote__echo", {"text": "write once"}) == "write once"
        assert agent._last_tool_result_metadata["mcp_idempotent_retries"] == 1
        assert state["tool_call_count"] == 2
        assert len(state["side_effects"]) == 1
        agent.mcp_clients["remote"].close()
