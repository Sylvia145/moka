"""Pico 自动化测试模块。

Tests are written against agent.validate_tool() so they remain valid
regardless of whether validation is implemented with ad-hoc checks or
Pydantic models underneath.
"""

import pytest

from pico.core.runtime import Pico
from pico.core.session_store import SessionStore
from pico.core.workspace import WorkspaceContext
from pico.testing import ScriptedModelClient


def build_workspace(tmp_path):
    """执行 `build_workspace` 的内部逻辑。"""
    (tmp_path / "README.md").write_text("demo\n", encoding="utf-8")
    return WorkspaceContext.build(tmp_path)


def build_agent(tmp_path, **kwargs):
    """执行 `build_agent` 的内部逻辑。"""
    workspace = build_workspace(tmp_path)
    store = SessionStore(tmp_path / ".pico" / "sessions")
    return Pico(
        model_client=ScriptedModelClient([]),
        workspace=workspace,
        session_store=store,
        approval_policy=kwargs.pop("approval_policy", "auto"),
        **kwargs,
    )


# ---------------------------------------------------------------------------
# 列出文件
# ---------------------------------------------------------------------------

class TestListFilesValidation:
    def test_valid_default_path(self, tmp_path):
        """执行 `test_valid_default_path` 的内部逻辑。"""
        agent = build_agent(tmp_path)
        agent.validate_tool("list_files", {})

    def test_valid_explicit_path(self, tmp_path):
        """执行 `test_valid_explicit_path` 的内部逻辑。"""
        agent = build_agent(tmp_path)
        agent.validate_tool("list_files", {"path": "."})

    def test_path_not_a_directory_raises(self, tmp_path):
        """执行 `test_path_not_a_directory_raises` 的内部逻辑。"""
        (tmp_path / "file.txt").write_text("x")
        agent = build_agent(tmp_path)
        with pytest.raises(ValueError, match="not a directory"):
            agent.validate_tool("list_files", {"path": "file.txt"})

    def test_nonexistent_path_raises(self, tmp_path):
        """执行 `test_nonexistent_path_raises` 的内部逻辑。"""
        agent = build_agent(tmp_path)
        with pytest.raises(ValueError):
            agent.validate_tool("list_files", {"path": "no_such_dir"})


# ---------------------------------------------------------------------------
# 读取文件
# ---------------------------------------------------------------------------

class TestReadFileValidation:
    def test_valid(self, tmp_path):
        """执行 `test_valid` 的内部逻辑。"""
        f = tmp_path / "a.py"
        f.write_text("x\n")
        agent = build_agent(tmp_path)
        agent.validate_tool("read_file", {"path": "a.py"})

    def test_valid_with_range(self, tmp_path):
        """执行 `test_valid_with_range` 的内部逻辑。"""
        f = tmp_path / "a.py"
        f.write_text("x\n" * 10)
        agent = build_agent(tmp_path)
        agent.validate_tool("read_file", {"path": "a.py", "start": 1, "end": 5})

    def test_missing_path_raises(self, tmp_path):
        """执行 `test_missing_path_raises` 的内部逻辑。"""
        agent = build_agent(tmp_path)
        with pytest.raises((ValueError, KeyError)):
            agent.validate_tool("read_file", {})

    def test_path_not_a_file_raises(self, tmp_path):
        """执行 `test_path_not_a_file_raises` 的内部逻辑。"""
        agent = build_agent(tmp_path)
        with pytest.raises(ValueError, match="not a file"):
            agent.validate_tool("read_file", {"path": "."})

    def test_start_less_than_one_raises(self, tmp_path):
        """执行 `test_start_less_than_one_raises` 的内部逻辑。"""
        f = tmp_path / "a.py"
        f.write_text("x\n")
        agent = build_agent(tmp_path)
        with pytest.raises(ValueError):
            agent.validate_tool("read_file", {"path": "a.py", "start": 0, "end": 10})

    def test_end_less_than_start_raises(self, tmp_path):
        """执行 `test_end_less_than_start_raises` 的内部逻辑。"""
        f = tmp_path / "a.py"
        f.write_text("x\n")
        agent = build_agent(tmp_path)
        with pytest.raises(ValueError):
            agent.validate_tool("read_file", {"path": "a.py", "start": 10, "end": 5})

    def test_path_escape_raises(self, tmp_path):
        """执行 `test_path_escape_raises` 的内部逻辑。"""
        agent = build_agent(tmp_path)
        with pytest.raises(ValueError):
            agent.validate_tool("read_file", {"path": "../outside.py"})


# ---------------------------------------------------------------------------
# 搜索
# ---------------------------------------------------------------------------

class TestSearchValidation:
    def test_valid(self, tmp_path):
        """执行 `test_valid` 的内部逻辑。"""
        agent = build_agent(tmp_path)
        agent.validate_tool("search", {"pattern": "foo"})

    def test_valid_with_path(self, tmp_path):
        """执行 `test_valid_with_path` 的内部逻辑。"""
        agent = build_agent(tmp_path)
        agent.validate_tool("search", {"pattern": "foo", "path": "."})

    def test_empty_pattern_raises(self, tmp_path):
        """执行 `test_empty_pattern_raises` 的内部逻辑。"""
        agent = build_agent(tmp_path)
        with pytest.raises(ValueError, match="pattern"):
            agent.validate_tool("search", {"pattern": ""})

    def test_whitespace_pattern_raises(self, tmp_path):
        """执行 `test_whitespace_pattern_raises` 的内部逻辑。"""
        agent = build_agent(tmp_path)
        with pytest.raises(ValueError, match="pattern"):
            agent.validate_tool("search", {"pattern": "   "})

    def test_missing_pattern_raises(self, tmp_path):
        """执行 `test_missing_pattern_raises` 的内部逻辑。"""
        agent = build_agent(tmp_path)
        with pytest.raises(ValueError):
            agent.validate_tool("search", {})


# ---------------------------------------------------------------------------
# 运行 Shell 命令
# ---------------------------------------------------------------------------

class TestRunShellValidation:
    def test_valid(self, tmp_path):
        """执行 `test_valid` 的内部逻辑。"""
        agent = build_agent(tmp_path)
        agent.validate_tool("run_shell", {"command": "echo hi"})

    def test_valid_with_timeout(self, tmp_path):
        """执行 `test_valid_with_timeout` 的内部逻辑。"""
        agent = build_agent(tmp_path)
        agent.validate_tool("run_shell", {"command": "echo hi", "timeout": 30})

    def test_empty_command_raises(self, tmp_path):
        """执行 `test_empty_command_raises` 的内部逻辑。"""
        agent = build_agent(tmp_path)
        with pytest.raises(ValueError, match="command"):
            agent.validate_tool("run_shell", {"command": ""})

    def test_whitespace_command_raises(self, tmp_path):
        """执行 `test_whitespace_command_raises` 的内部逻辑。"""
        agent = build_agent(tmp_path)
        with pytest.raises(ValueError, match="command"):
            agent.validate_tool("run_shell", {"command": "  "})

    def test_missing_command_raises(self, tmp_path):
        """执行 `test_missing_command_raises` 的内部逻辑。"""
        agent = build_agent(tmp_path)
        with pytest.raises(ValueError):
            agent.validate_tool("run_shell", {})

    def test_timeout_too_low_raises(self, tmp_path):
        """执行 `test_timeout_too_low_raises` 的内部逻辑。"""
        agent = build_agent(tmp_path)
        with pytest.raises(ValueError, match="timeout"):
            agent.validate_tool("run_shell", {"command": "echo hi", "timeout": 0})

    def test_timeout_too_high_raises(self, tmp_path):
        """执行 `test_timeout_too_high_raises` 的内部逻辑。"""
        agent = build_agent(tmp_path)
        with pytest.raises(ValueError, match="timeout"):
            agent.validate_tool("run_shell", {"command": "echo hi", "timeout": 121})

    def test_timeout_at_boundaries_valid(self, tmp_path):
        """执行 `test_timeout_at_boundaries_valid` 的内部逻辑。"""
        agent = build_agent(tmp_path)
        agent.validate_tool("run_shell", {"command": "echo hi", "timeout": 1})
        agent.validate_tool("run_shell", {"command": "echo hi", "timeout": 120})


# ---------------------------------------------------------------------------
# 写入文件
# ---------------------------------------------------------------------------

class TestWriteFileValidation:
    def test_valid_new_file(self, tmp_path):
        """执行 `test_valid_new_file` 的内部逻辑。"""
        agent = build_agent(tmp_path)
        agent.validate_tool("write_file", {"path": "new.py", "content": "x"})

    def test_valid_existing_file(self, tmp_path):
        """执行 `test_valid_existing_file` 的内部逻辑。"""
        (tmp_path / "existing.py").write_text("old")
        agent = build_agent(tmp_path)
        # 已存在文件允许写入（覆盖）
        agent.validate_tool("write_file", {"path": "existing.py", "content": "new"})

    def test_missing_content_raises(self, tmp_path):
        """执行 `test_missing_content_raises` 的内部逻辑。"""
        agent = build_agent(tmp_path)
        with pytest.raises(ValueError, match="content"):
            agent.validate_tool("write_file", {"path": "x.py"})

    def test_missing_path_raises(self, tmp_path):
        """执行 `test_missing_path_raises` 的内部逻辑。"""
        agent = build_agent(tmp_path)
        with pytest.raises((ValueError, KeyError)):
            agent.validate_tool("write_file", {"content": "x"})

    def test_path_is_directory_raises(self, tmp_path):
        """执行 `test_path_is_directory_raises` 的内部逻辑。"""
        (tmp_path / "mydir").mkdir()
        agent = build_agent(tmp_path)
        with pytest.raises(ValueError, match="directory"):
            agent.validate_tool("write_file", {"path": "mydir", "content": "x"})

    def test_path_escape_raises(self, tmp_path):
        """执行 `test_path_escape_raises` 的内部逻辑。"""
        agent = build_agent(tmp_path)
        with pytest.raises(ValueError):
            agent.validate_tool("write_file", {"path": "../escape.py", "content": "x"})


# ---------------------------------------------------------------------------
# 补丁修改文件
# ---------------------------------------------------------------------------

class TestPatchFileValidation:
    def test_valid(self, tmp_path):
        """执行 `test_valid` 的内部逻辑。"""
        f = tmp_path / "a.py"
        f.write_text("def foo():\n    return 1\n")
        agent = build_agent(tmp_path)
        agent.validate_tool("patch_file", {
            "path": "a.py",
            "old_text": "return 1",
            "new_text": "return 2",
        })

    def test_missing_path_raises(self, tmp_path):
        """执行 `test_missing_path_raises` 的内部逻辑。"""
        agent = build_agent(tmp_path)
        with pytest.raises((ValueError, KeyError)):
            agent.validate_tool("patch_file", {"old_text": "x", "new_text": "y"})

    def test_path_not_a_file_raises(self, tmp_path):
        """执行 `test_path_not_a_file_raises` 的内部逻辑。"""
        agent = build_agent(tmp_path)
        with pytest.raises(ValueError, match="not a file"):
            agent.validate_tool("patch_file", {"path": "no_such.py", "old_text": "x", "new_text": "y"})

    def test_empty_old_text_raises(self, tmp_path):
        """执行 `test_empty_old_text_raises` 的内部逻辑。"""
        f = tmp_path / "a.py"
        f.write_text("x\n")
        agent = build_agent(tmp_path)
        with pytest.raises(ValueError, match="old_text"):
            agent.validate_tool("patch_file", {"path": "a.py", "old_text": "", "new_text": "y"})

    def test_missing_new_text_raises(self, tmp_path):
        """执行 `test_missing_new_text_raises` 的内部逻辑。"""
        f = tmp_path / "a.py"
        f.write_text("x\n")
        agent = build_agent(tmp_path)
        with pytest.raises(ValueError, match="new_text"):
            agent.validate_tool("patch_file", {"path": "a.py", "old_text": "x"})

    def test_old_text_not_found_raises(self, tmp_path):
        """执行 `test_old_text_not_found_raises` 的内部逻辑。"""
        f = tmp_path / "a.py"
        f.write_text("hello\n")
        agent = build_agent(tmp_path)
        with pytest.raises(ValueError, match="exactly once"):
            agent.validate_tool("patch_file", {"path": "a.py", "old_text": "world", "new_text": "y"})

    def test_old_text_found_multiple_times_raises(self, tmp_path):
        """执行 `test_old_text_found_multiple_times_raises` 的内部逻辑。"""
        f = tmp_path / "a.py"
        f.write_text("x\nx\n")
        agent = build_agent(tmp_path)
        with pytest.raises(ValueError, match="exactly once"):
            agent.validate_tool("patch_file", {"path": "a.py", "old_text": "x", "new_text": "y"})


# ---------------------------------------------------------------------------
# 待办工具
# ---------------------------------------------------------------------------

class TestTodoValidation:
    def test_todo_add_valid(self, tmp_path):
        """执行 `test_todo_add_valid` 的内部逻辑。"""
        agent = build_agent(tmp_path)
        agent.validate_tool("todo_add", {"content": "Do something"})

    def test_todo_add_empty_content_raises(self, tmp_path):
        """执行 `test_todo_add_empty_content_raises` 的内部逻辑。"""
        agent = build_agent(tmp_path)
        with pytest.raises(ValueError, match="content"):
            agent.validate_tool("todo_add", {"content": ""})

    def test_todo_add_whitespace_content_raises(self, tmp_path):
        """执行 `test_todo_add_whitespace_content_raises` 的内部逻辑。"""
        agent = build_agent(tmp_path)
        with pytest.raises(ValueError, match="content"):
            agent.validate_tool("todo_add", {"content": "  "})

    def test_todo_update_valid(self, tmp_path):
        """执行 `test_todo_update_valid` 的内部逻辑。"""
        agent = build_agent(tmp_path)
        agent.validate_tool("todo_update", {"todo_id": "todo_1", "status": "done"})

    def test_todo_update_empty_id_raises(self, tmp_path):
        """执行 `test_todo_update_empty_id_raises` 的内部逻辑。"""
        agent = build_agent(tmp_path)
        with pytest.raises(ValueError, match="todo_id"):
            agent.validate_tool("todo_update", {"todo_id": ""})

    def test_todo_list_valid(self, tmp_path):
        """执行 `test_todo_list_valid` 的内部逻辑。"""
        agent = build_agent(tmp_path)
        agent.validate_tool("todo_list", {})


# ---------------------------------------------------------------------------
# 子代理 / 发送消息 / 停止任务
# ---------------------------------------------------------------------------

class TestAgentToolValidation:
    def test_agent_valid(self, tmp_path):
        """执行 `test_agent_valid` 的内部逻辑。"""
        agent = build_agent(tmp_path)
        agent.validate_tool("agent", {
            "description": "Explore auth",
            "prompt": "Find entry points",
            "subagent_type": "Explore",
        })

    def test_agent_empty_description_raises(self, tmp_path):
        """执行 `test_agent_empty_description_raises` 的内部逻辑。"""
        agent = build_agent(tmp_path)
        with pytest.raises(ValueError, match="description"):
            agent.validate_tool("agent", {"description": "", "prompt": "do it"})

    def test_agent_empty_prompt_raises(self, tmp_path):
        """执行 `test_agent_empty_prompt_raises` 的内部逻辑。"""
        agent = build_agent(tmp_path)
        with pytest.raises(ValueError, match="prompt"):
            agent.validate_tool("agent", {"description": "x", "prompt": ""})

    def test_agent_invalid_subagent_type_raises(self, tmp_path):
        """执行 `test_agent_invalid_subagent_type_raises` 的内部逻辑。"""
        agent = build_agent(tmp_path)
        with pytest.raises(ValueError, match="subagent_type"):
            agent.validate_tool("agent", {
                "description": "x", "prompt": "y", "subagent_type": "invalid"
            })

    def test_agent_invalid_write_scope_raises(self, tmp_path):
        """执行 `test_agent_invalid_write_scope_raises` 的内部逻辑。"""
        agent = build_agent(tmp_path)
        with pytest.raises(ValueError, match="write_scope"):
            agent.validate_tool("agent", {
                "description": "x", "prompt": "y", "write_scope": 42
            })

    def test_send_message_valid(self, tmp_path):
        """执行 `test_send_message_valid` 的内部逻辑。"""
        agent = build_agent(tmp_path)
        agent.validate_tool("send_message", {"to": "worker_1", "message": "continue"})

    def test_send_message_empty_to_raises(self, tmp_path):
        """执行 `test_send_message_empty_to_raises` 的内部逻辑。"""
        agent = build_agent(tmp_path)
        with pytest.raises(ValueError, match="to"):
            agent.validate_tool("send_message", {"to": "", "message": "hi"})

    def test_send_message_empty_message_raises(self, tmp_path):
        """执行 `test_send_message_empty_message_raises` 的内部逻辑。"""
        agent = build_agent(tmp_path)
        with pytest.raises(ValueError, match="message"):
            agent.validate_tool("send_message", {"to": "w1", "message": ""})

    def test_task_stop_valid(self, tmp_path):
        """执行 `test_task_stop_valid` 的内部逻辑。"""
        agent = build_agent(tmp_path)
        agent.validate_tool("task_stop", {"task_id": "task_abc"})

    def test_task_stop_empty_id_raises(self, tmp_path):
        """执行 `test_task_stop_empty_id_raises` 的内部逻辑。"""
        agent = build_agent(tmp_path)
        with pytest.raises(ValueError, match="task_id"):
            agent.validate_tool("task_stop", {"task_id": ""})


# ---------------------------------------------------------------------------
# 计划模式工具
# ---------------------------------------------------------------------------

class TestPlanToolValidation:
    def test_enter_plan_mode_valid(self, tmp_path):
        """执行 `test_enter_plan_mode_valid` 的内部逻辑。"""
        agent = build_agent(tmp_path)
        agent.validate_tool("enter_plan_mode", {"topic": "Refactor auth"})

    def test_enter_plan_mode_empty_topic_raises(self, tmp_path):
        """执行 `test_enter_plan_mode_empty_topic_raises` 的内部逻辑。"""
        agent = build_agent(tmp_path)
        with pytest.raises(ValueError, match="topic"):
            agent.validate_tool("enter_plan_mode", {"topic": ""})

    def test_exit_plan_mode_valid(self, tmp_path):
        """执行 `test_exit_plan_mode_valid` 的内部逻辑。"""
        agent = build_agent(tmp_path)
        agent.validate_tool("exit_plan_mode", {})


# ---------------------------------------------------------------------------
# 向用户提问
# ---------------------------------------------------------------------------

class TestAskUserValidation:
    def test_valid(self, tmp_path):
        """执行 `test_valid` 的内部逻辑。"""
        agent = build_agent(tmp_path)
        agent.validate_tool("ask_user", {"question": "Which env?"})

    def test_valid_with_choices(self, tmp_path):
        """执行 `test_valid_with_choices` 的内部逻辑。"""
        agent = build_agent(tmp_path)
        agent.validate_tool("ask_user", {"question": "Which env?", "choices": ["dev", "prod"]})

    def test_empty_question_raises(self, tmp_path):
        """执行 `test_empty_question_raises` 的内部逻辑。"""
        agent = build_agent(tmp_path)
        with pytest.raises(ValueError, match="question"):
            agent.validate_tool("ask_user", {"question": ""})

    def test_choices_not_a_list_raises(self, tmp_path):
        """执行 `test_choices_not_a_list_raises` 的内部逻辑。"""
        agent = build_agent(tmp_path)
        with pytest.raises(ValueError, match="choices"):
            agent.validate_tool("ask_user", {"question": "Which?", "choices": "dev"})
