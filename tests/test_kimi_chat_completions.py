"""Kimi/Moonshot 集成测试。

覆盖两件事：
1. `kimi` 作为一等 provider 的配置解析（别名、协议、显式 toml 与通用环境变量）；
2. `ChatCompletionsModelClient` 走 `/chat/completions` 且用 `messages`+`max_tokens`
   请求体（区别于 Responses 接口的 `input`+`max_output_tokens`）。
"""
import json

from pico.config import normalize_provider_name, resolve_provider_config
from pico.providers.clients import ChatCompletionsModelClient


def test_moonshot_alias_normalizes_to_kimi():
    assert normalize_provider_name("moonshot") == "kimi"
    assert normalize_provider_name("KIMI") == "kimi"


def test_kimi_config_resolves_openai_chat_protocol(tmp_path):
    (tmp_path / ".pico.toml").write_text(
        '[providers.kimi]\n'
        'protocol = "openai_chat"\n'
        'api_key = "sk-from-toml"\n'
        'base_url = "https://api.moonshot.cn/v1"\n'
        'model = "moonshot-v1-128k"\n',
        encoding="utf-8",
    )

    config = resolve_provider_config("kimi", start=tmp_path)

    assert config.name == "kimi"
    assert config.protocol == "openai_chat"
    assert config.base_url == "https://api.moonshot.cn/v1"
    assert config.model == "moonshot-v1-128k"
    assert config.api_key == "sk-from-toml"
    assert config.supports_vision is False


def test_kimi_generic_env_used_without_toml(tmp_path, monkeypatch):
    monkeypatch.setenv("KIMI_API_KEY", "sk-generic")

    config = resolve_provider_config("kimi", start=tmp_path)

    assert config.api_key == "sk-generic"
    assert config.protocol == "openai_chat"


def test_chat_completions_client_sends_messages_payload(monkeypatch):
    captured = {}

    def fake_request_with_retries(provider, model, base_url, request, timeout, retry_budget=2):
        del retry_budget
        captured["provider"] = provider
        captured["model"] = model
        captured["url"] = request.full_url
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        body = json.dumps(
            {
                "choices": [{"message": {"content": "贪心算法是每一步都取当前最优"}}],
                "usage": {"input_tokens": 14, "output_tokens": 36, "total_tokens": 50},
            }
        )
        return body, "application/json", {"status": "ok"}

    monkeypatch.setattr(
        "pico.providers.clients._request_with_retries", fake_request_with_retries
    )

    client = ChatCompletionsModelClient(
        model="moonshot-v1-128k",
        base_url="https://api.moonshot.cn/v1",
        api_key="sk-test",
        temperature=0,
        timeout=30,
    )
    text = client.complete("用一句话解释什么是贪心算法", max_new_tokens=64)

    assert text == "贪心算法是每一步都取当前最优"
    assert captured["provider"] == "openai_chat"
    assert captured["url"].endswith("/chat/completions")
    # 请求体必须用 Chat Completions 的字段，而不是 Responses 的字段。
    assert "messages" in captured["payload"]
    assert "input" not in captured["payload"]
    assert "max_tokens" in captured["payload"]
    assert "max_output_tokens" not in captured["payload"]
    assert captured["payload"]["max_tokens"] == 64
    assert captured["payload"]["temperature"] == 0
    # provider-billed 用量被整理成统一结构。
    assert client.last_completion_metadata["input_tokens"] == 14
    assert client.last_completion_metadata["output_tokens"] == 36
    assert client.last_completion_metadata["total_tokens"] == 50
