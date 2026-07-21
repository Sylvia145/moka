"""Pico 运行时实现模块。"""

import os
import sys

SENSITIVE_ENV_NAME_MARKERS = ("API_KEY", "TOKEN", "SECRET", "PASSWORD")
REDACTED_VALUE = "<redacted>"

# Windows 上的 `subprocess.run(..., shell=True)` 依赖这些变量定位 cmd.exe 和
# 系统目录。它们不包含机密；但若过滤后的环境遗漏它们，子进程仍会执行却报告
# 错误的非零退出码。因此不要把它们纳入敏感变量白名单，仅在 Windows 中补回。
WINDOWS_SHELL_ENV_NAMES = (
    "ComSpec",
    "SystemRoot",
    "SystemDrive",
    "PATHEXT",
    "WINDIR",
    "ProgramFiles",
)


class RuntimeSecretsMixin:
    @staticmethod
    def looks_sensitive_env_name(name):
        """执行 `looks_sensitive_env_name` 的内部逻辑。"""
        upper = str(name).upper()
        return any(upper == marker or upper.endswith(marker) or upper.endswith(f"_{marker}") for marker in SENSITIVE_ENV_NAME_MARKERS)

    def is_secret_env_name(self, name):
        """执行 `is_secret_env_name` 的内部逻辑。"""
        upper = str(name).upper()
        return upper in self.secret_env_names or self.looks_sensitive_env_name(upper)

    def configured_secret_env_items(self):
        """执行 `configured_secret_env_items` 的内部逻辑。"""
        items = [(name, value) for name, value in os.environ.items() if str(name).upper() in self.secret_env_names and value]
        items.sort(key=lambda item: item[0])
        return items

    def detected_secret_env_items(self):
        """执行 `detected_secret_env_items` 的内部逻辑。"""
        items = [(name, value) for name, value in os.environ.items() if self.is_secret_env_name(name) and value]
        items.sort(key=lambda item: item[0])
        return items

    def secret_env_summary(self):
        """执行 `secret_env_summary` 的内部逻辑。"""
        names = [name for name, _ in self.configured_secret_env_items()]
        return {"secret_env_count": len(names), "secret_env_names": names}

    def detected_secret_env_summary(self):
        """执行 `detected_secret_env_summary` 的内部逻辑。"""
        names = [name for name, _ in self.detected_secret_env_items()]
        return {"secret_env_count": len(names), "secret_env_names": names}

    def redact_text(self, text):
        """执行 `redact_text` 的内部逻辑。"""
        text = str(text)
        for _, value in sorted(self.detected_secret_env_items(), key=lambda item: len(item[1]), reverse=True):
            text = text.replace(value, REDACTED_VALUE)
        return text

    def redact_artifact(self, value, key=None):
        """执行 `redact_artifact` 的内部逻辑。"""
        if key and self.is_secret_env_name(key):
            return REDACTED_VALUE
        if isinstance(value, dict):
            return {str(item_key): self.redact_artifact(item_value, key=item_key) for item_key, item_value in value.items()}
        if isinstance(value, list):
            return [self.redact_artifact(item, key=key) for item in value]
        if isinstance(value, tuple):
            return [self.redact_artifact(item, key=key) for item in value]
        if isinstance(value, str):
            return self.redact_text(value)
        return value

    def shell_env(self):
        """执行 `shell_env` 的内部逻辑。"""
        env = {name: os.environ[name] for name in self.shell_env_allowlist if name in os.environ}
        if sys.platform == "win32":
            for name in WINDOWS_SHELL_ENV_NAMES:
                if name in os.environ:
                    env.setdefault(name, os.environ[name])
        env["PWD"] = str(self.root)
        if "PATH" not in env and os.environ.get("PATH"):
            env["PATH"] = os.environ["PATH"]
        return env
