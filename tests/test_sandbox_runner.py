"""Pico 自动化测试模块。"""
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

from pico.features.sandbox.config import SandboxConfig
from pico.features.sandbox.runner import SandboxRunner


def test_required_sandbox_rejects_when_backend_is_unavailable(tmp_path):
    """执行 `test_required_sandbox_rejects_when_backend_is_unavailable` 的内部逻辑。"""
    runner = SandboxRunner(
        SandboxConfig(mode="required", backend="bubblewrap"), which=lambda name: None
    )

    with pytest.raises(RuntimeError, match="sandbox required but unavailable"):
        runner.run("echo hi", cwd=tmp_path, env={}, timeout=5)


def test_required_sandbox_does_not_honor_excluded_commands(tmp_path):
    """执行 `test_required_sandbox_does_not_honor_excluded_commands` 的内部逻辑。"""
    runner = SandboxRunner(
        SandboxConfig(mode="required", backend="bubblewrap", excluded_commands=("*",)),
        which=lambda name: None,
    )

    with pytest.raises(RuntimeError, match="sandbox required but unavailable"):
        runner.run("echo hi", cwd=tmp_path, env={}, timeout=5)


def test_best_effort_sandbox_records_degrade_and_runs_without_backend(tmp_path):
    """执行 `test_best_effort_sandbox_records_degrade_and_runs_without_backend` 的内部逻辑。"""
    events = []
    runner = SandboxRunner(
        SandboxConfig(mode="best_effort", backend="bubblewrap"),
        which=lambda name: None,
        emit_event=lambda event, payload: events.append((event, payload)),
    )

    if sys.platform == "win32":
        command = f'"{sys.executable}" -c "print(42)"'
    else:
        command = f"{sys.executable} -c 'print(42)'"
    result = runner.run(
        command,
        cwd=tmp_path,
        env=os.environ.copy(),
        timeout=5,
    )

    assert result.returncode == 0
    assert result.stdout.strip() == "42"
    assert events[0][0] == "sandbox_unavailable"


def test_off_sandbox_keeps_plain_subprocess_behavior(tmp_path):
    """执行 `test_off_sandbox_keeps_plain_subprocess_behavior` 的内部逻辑。"""
    runner = SandboxRunner(SandboxConfig(mode="off"), run=subprocess.run)

    command = "cd" if sys.platform == "win32" else "pwd"
    result = runner.run(command, cwd=tmp_path, env=os.environ.copy(), timeout=5)

    assert Path(result.stdout.strip()) == tmp_path


def test_plain_runner_uses_utf8_with_replacement_for_captured_output(tmp_path):
    """执行 `test_plain_runner_uses_utf8_with_replacement_for_captured_output` 的内部逻辑。"""
    fake_run = Mock(
        return_value=type("Result", (), {"returncode": 0, "stdout": "ok", "stderr": ""})()
    )
    runner = SandboxRunner(SandboxConfig(mode="off"), run=fake_run)

    runner.run("echo hi", cwd=tmp_path, env={}, timeout=5)

    assert fake_run.call_args.kwargs["encoding"] == "utf-8"
    assert fake_run.call_args.kwargs["errors"] == "replace"
