"""Provider 配置优先级测试。

核心断言：`.pico.toml` 的显式配置优先于通用环境变量（ANTHROPIC_MODEL、
ANTHROPIC_BASE_URL、ANTHROPIC_AUTH_TOKEN 等）。这些通用名可能被宿主进程
（Claude Code 用 DeepSeek 后端时会注入 ANTHROPIC_*）静默覆盖项目配置。
"""
from pico.config import resolve_provider_config


def test_explicit_toml_beats_generic_model_and_base_url(tmp_path, monkeypatch):
    (tmp_path / ".pico.toml").write_text(
        '[providers.anthropic]\n'
        'protocol = "anthropic"\n'
        'model = "claude-sonnet-4-6"\n'
        'base_url = "https://www.right.codes/claude/v1"\n',
        encoding="utf-8",
    )
    # 模拟宿主注入的通用变量，指向 DeepSeek 后端。
    monkeypatch.setenv("ANTHROPIC_MODEL", "deepseek-v4-pro")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://api.deepseek.com/anthropic")

    config = resolve_provider_config("anthropic", start=tmp_path)

    assert config.model == "claude-sonnet-4-6"
    assert config.base_url == "https://www.right.codes/claude/v1"


def test_explicit_toml_beats_generic_api_key(tmp_path, monkeypatch):
    (tmp_path / ".pico.toml").write_text(
        '[providers.anthropic]\n'
        'protocol = "anthropic"\n'
        'api_key = "sk-from-toml"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "sk-from-host")

    config = resolve_provider_config("anthropic", start=tmp_path)

    assert config.api_key == "sk-from-toml"


def test_generic_env_still_used_without_toml(tmp_path, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-generic")

    config = resolve_provider_config("deepseek", start=tmp_path)

    assert config.api_key == "sk-generic"


def test_generic_model_env_still_used_without_toml(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_MODEL", "custom-model")

    config = resolve_provider_config("openai", start=tmp_path)

    assert config.model == "custom-model"
