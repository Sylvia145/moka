"""Pico 运行时实现模块。"""

from dataclasses import dataclass

SANDBOX_MODES = {"off", "best_effort", "required"}
SANDBOX_BACKENDS = {"auto", "bubblewrap", "none"}


@dataclass(frozen=True)
class SandboxConfig:
    mode: str = "off"
    backend: str = "auto"
    workspace_write: bool = True
    excluded_commands: tuple[str, ...] = ()
    extra_readonly_paths: tuple[str, ...] = ()
    deny_read: tuple[str, ...] = ()
    deny_write: tuple[str, ...] = ()

    @property
    def enabled(self):
        """执行 `enabled` 的内部逻辑。"""
        return self.mode != "off"


def resolve_sandbox_config(values):
    """执行 `resolve_sandbox_config` 的内部逻辑。"""
    sandbox = dict((values or {}).get("sandbox", {}) or {})
    filesystem = dict(sandbox.get("filesystem", {}) or {})
    mode = str(sandbox.get("mode", "off") or "off")
    backend = str(sandbox.get("backend", "auto") or "auto")
    if mode not in SANDBOX_MODES:
        raise ValueError(f"sandbox.mode must be one of {sorted(SANDBOX_MODES)}")
    if backend not in SANDBOX_BACKENDS:
        raise ValueError(f"sandbox.backend must be one of {sorted(SANDBOX_BACKENDS)}")
    return SandboxConfig(
        mode=mode,
        backend=backend,
        workspace_write=bool(sandbox.get("workspace_write", True)),
        excluded_commands=tuple(
            str(item) for item in sandbox.get("excluded_commands", []) or []
        ),
        extra_readonly_paths=tuple(
            str(item) for item in filesystem.get("extra_readonly_paths", []) or []
        ),
        deny_read=tuple(str(item) for item in filesystem.get("deny_read", []) or []),
        deny_write=tuple(str(item) for item in filesystem.get("deny_write", []) or []),
    )
