"""MCP 远程故障注入与幂等重试（手册 Phase 8）。

逐场景运行 A–K，输出故障注入矩阵与幂等重试对照，用于填充
docs/benchmark/MCP远程故障注入与幂等重试.md。不使用真实模型。

用法：PYTHONIOENCODING=utf-8 uv run python scripts/mcp_http_fault_injection.py
"""

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pico.evaluation.mcp_http_fault_server import http_mcp_server
from pico.tools import McpServerConfig
from pico.tools.mcp import create_mcp_client
from pico.tools.mcp_http import McpHttpError, McpOutcomeUnknownError

WIDTH = 26


def _config(url, **kwargs):
    return McpServerConfig("remote", transport="streamable_http", url=url, timeout=0.05, **kwargs)


def _run_call(client):
    """执行一次 tools/call，返回 (outcome, cause, result)。"""
    try:
        result = client.call_tool("echo", {"text": "write once"})
        return "ok", "", result
    except McpOutcomeUnknownError as exc:
        return "mcp_outcome_unknown", exc.cause_code, None
    except McpHttpError as exc:
        return exc.code, "", None


def _counts(state):
    calls = sum(1 for c in state["calls"] if c["request"]["method"] == "tools/call")
    return calls, len(state["side_effects"])


def _list_info(state):
    return sum(1 for c in state["calls"] if c["request"]["method"] == "tools/list")


def run_scenarios():
    results = []

    # A 读基线：json，list_tools 正常
    with http_mcp_server() as (state, url):
        client = create_mcp_client(_config(url))
        assert len(client.list_tools()) == 1
        results.append(["A 读基线", "json", "off", 0, 0, "ok", f"list×{_list_info(state)}"])
        client.close()

    # B 读重试：5xx×2 后成功
    with http_mcp_server(list_failures=2) as (state, url):
        client = create_mcp_client(_config(url, max_retries=3))
        assert client.list_tools()[0]["name"] == "echo"
        assert _list_info(state) == 3
        results.append(["B 读重试·5xx×2后成功", "list_failures=2", "off", 0, 0, "ok", f"list×{_list_info(state)}"])
        client.close()

    # C 读会话过期恢复
    with http_mcp_server(expire_first=True) as (state, url):
        client = create_mcp_client(_config(url, max_retries=1))
        assert client.list_tools()[0]["name"] == "echo"
        assert state["initialize_count"] == 2
        results.append(["C 读会话过期恢复", "expire_first", "off", 0, 0, "ok", f"init×{state['initialize_count']}"])
        client.close()

    # D 写·超时·幂等关
    with http_mcp_server("timeout") as (state, url):
        client = create_mcp_client(_config(url))
        outcome, cause, _ = _run_call(client)
        calls, effects = _counts(state)
        assert outcome == "mcp_outcome_unknown" and cause == "mcp_http_timeout"
        assert calls == 1 and effects == 1
        results.append(["D 写·超时·幂等关", "timeout", "off", calls, effects, outcome, cause])
        client.close()

    # E 写·断连·幂等关
    with http_mcp_server("disconnect") as (state, url):
        client = create_mcp_client(_config(url))
        outcome, cause, _ = _run_call(client)
        calls, effects = _counts(state)
        assert outcome == "mcp_outcome_unknown" and cause == "mcp_http_connect_failed"
        assert calls == 1 and effects == 1
        results.append(["E 写·断连·幂等关", "disconnect", "off", calls, effects, outcome, cause])
        client.close()

    # F 写·截断·幂等关
    with http_mcp_server("truncated") as (state, url):
        client = create_mcp_client(_config(url))
        outcome, cause, _ = _run_call(client)
        calls, effects = _counts(state)
        assert outcome == "mcp_outcome_unknown" and cause == "mcp_invalid_response"
        assert calls == 1 and effects == 1
        results.append(["F 写·截断·幂等关", "truncated", "off", calls, effects, outcome, cause])
        client.close()

    # G 写·5xx·幂等关
    with http_mcp_server("server_error") as (state, url):
        client = create_mcp_client(_config(url))
        outcome, cause, _ = _run_call(client)
        calls, effects = _counts(state)
        assert outcome == "mcp_outcome_unknown" and cause == "mcp_http_server_error"
        assert calls == 1 and effects == 1
        results.append(["G 写·5xx·幂等关", "server_error", "off", calls, effects, outcome, cause])
        client.close()

    # H 写·断连·幂等开·服务端去重：重试恢复，副作用精确一次
    with http_mcp_server("disconnect", fail_first_call=True) as (state, url):
        client = create_mcp_client(_config(url, max_idempotent_retries=1))
        outcome, cause, result = _run_call(client)
        calls, effects = _counts(state)
        assert outcome == "ok" and result["content"][0]["text"] == "write once"
        assert calls == 2 and effects == 1 and state["dedup_hits"] == 1
        assert client.last_idempotent_retries == 1
        results.append(["H 写·断连·幂等开·去重", "disconnect+dedup", "on", calls, effects, outcome, f"dedup={state['dedup_hits']}"])
        client.close()

    # I 写·断连·幂等开·服务端不去重：第 2 次裸执行，副作用×2（风险）
    with http_mcp_server("disconnect", fail_first_call=True, dedup_idempotent=False) as (state, url):
        client = create_mcp_client(_config(url, max_idempotent_retries=1))
        outcome, cause, result = _run_call(client)
        calls, effects = _counts(state)
        assert outcome == "ok" and result["content"][0]["text"] == "write once"
        assert calls == 2 and effects == 2 and state["dedup_hits"] == 0
        assert client.last_idempotent_retries == 1
        results.append(["I 写·断连·幂等开·不去重", "disconnect+no-dedup", "on", calls, effects, outcome, "side-effect×2"])
        client.close()

    # J 写·响应过大·不重试
    with http_mcp_server("large") as (state, url):
        # 1024B 能容纳握手(约140B)，仅 tools/call 的 large 响应(8192B)被拒。
        client = create_mcp_client(_config(url, max_response_bytes=1024))
        outcome, cause, _ = _run_call(client)
        calls, effects = _counts(state)
        assert outcome == "mcp_response_too_large"
        assert calls == 1 and effects == 1 and client.last_idempotent_retries == 0
        results.append(["J 写·响应过大·不重试", "large+1024B", "off", calls, effects, outcome, ""])
        client.close()

    # K 写·未授权·不重试
    os.environ.pop("MOKA_FAULT_INJECTION_NO_TOKEN", None)
    with http_mcp_server(require_token="good") as (state, url):
        client = create_mcp_client(_config(url, token_env="MOKA_FAULT_INJECTION_NO_TOKEN", max_idempotent_retries=1))
        outcome, cause, _ = _run_call(client)
        calls, effects = _counts(state)
        assert outcome == "mcp_http_unauthorized"
        assert calls == 0 and effects == 0 and client.last_idempotent_retries == 0
        results.append(["K 写·未授权·不重试", "401", "on", calls, effects, outcome, ""])
        client.close()

    return results


def main():
    print("=== MCP 远程故障注入与幂等重试报告 ===")
    print("运行时间:", time.strftime("%Y-%m-%d %H:%M:%S"))
    results = run_scenarios()
    header = ["label", "fault", "idem", "calls_received", "side_effects", "outcome", "cause"]
    print("\n" + "|".join(h.ljust(WIDTH) for h in header))
    for row in results:
        print("|".join(str(c).ljust(WIDTH) for c in row))
    print("\n结论：")
    print("D–G 结果未知且未重试（side_effects=1），证明默认\"写不重试\"契约；")
    print("H vs I 对照：服务端按 Idempotency-Key 去重时 side_effects=1（幂等重试安全），")
    print("服务端忽略该头时 side_effects=2（重试仅在服务端配合时安全）；")
    print("J/K：response_too_large 与 unauthorized 不在重试集合内，未被重试；")
    print("A–C：读路径重试/会话恢复不受影响。")


if __name__ == "__main__":
    main()
