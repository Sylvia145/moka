import pytest

from pico import Pico, SessionStore, WorkspaceContext
from pico.testing import ScriptedModelClient


def build_agent(tmp_path, outputs, approval_policy="auto"):
    (tmp_path / "README.md").write_text("demo\n", encoding="utf-8")
    workspace = WorkspaceContext.build(tmp_path)
    return Pico(
        model_client=ScriptedModelClient(outputs),
        workspace=workspace,
        session_store=SessionStore(tmp_path / ".pico" / "sessions"),
        approval_policy=approval_policy,
    )


def assistant_contents(app):
    from pico.tui.widgets import AssistantMessage

    return [message.content for message in app.query(AssistantMessage)]


def rendered_text(widget) -> str:
    rendered = widget.render()
    return getattr(rendered, "plain", str(rendered))


def test_cli_defaults_interactive_tty_mode_to_tui(monkeypatch):
    from pico.cli import build_arg_parser, interaction_mode

    monkeypatch.setattr("pico.cli.sys.stdin", type("Stdin", (), {"isatty": lambda self: True})())
    args = build_arg_parser().parse_args(["--cwd", "/tmp/workspace"])

    assert interaction_mode(args) == "tui"


def test_cli_keeps_prompt_as_one_shot_mode():
    from pico.cli import build_arg_parser, interaction_mode

    args = build_arg_parser().parse_args(["inspect", "tests"])

    assert interaction_mode(args) == "one_shot"


def test_cli_repl_flag_restores_plain_repl():
    from pico.cli import build_arg_parser, interaction_mode

    args = build_arg_parser().parse_args(["--repl", "--cwd", "/tmp/workspace"])

    assert interaction_mode(args) == "repl"


def test_cli_uses_plain_repl_for_piped_stdin(monkeypatch):
    from pico.cli import build_arg_parser, interaction_mode

    monkeypatch.setattr("pico.cli.sys.stdin", type("Stdin", (), {"isatty": lambda self: False})())
    args = build_arg_parser().parse_args(["--cwd", "/tmp/workspace"])

    assert interaction_mode(args) == "repl"


def test_cli_accepts_explicit_tui_flag():
    from pico.cli import build_arg_parser, interaction_mode

    args = build_arg_parser().parse_args(["--tui", "--cwd", "/tmp/workspace"])

    assert args.tui is True
    assert interaction_mode(args) == "tui"
    assert args.cwd == "/tmp/workspace"


def test_status_bar_shows_runtime_identity(tmp_path):
    from pico.tui.widgets import StatusBar

    agent = build_agent(tmp_path, [])
    status = StatusBar()

    status.update_agent(agent)

    text = rendered_text(status)
    assert "mode default" in text
    assert "session" in text


@pytest.mark.asyncio
async def test_tui_help_command_uses_existing_repl_commands(tmp_path):
    from pico.tui.app import PicoTuiApp
    from pico.tui.widgets import InputBar

    agent = build_agent(tmp_path, [])
    app = PicoTuiApp(agent)

    async with app.run_test() as pilot:
        bar = app.query_one(InputBar)
        bar.input.value = "/help"
        await pilot.press("enter")
        await pilot.pause(delay=0.1)

        text = "\n".join(assistant_contents(app))
        assert "Commands:" in text
        assert "/memory" in text


@pytest.mark.asyncio
async def test_tui_runs_agent_turn_and_renders_final_answer(tmp_path):
    from pico.tui.app import PicoTuiApp
    from pico.tui.widgets import InputBar

    agent = build_agent(tmp_path, ["<final>Done from TUI.</final>"])
    app = PicoTuiApp(agent)

    async with app.run_test() as pilot:
        bar = app.query_one(InputBar)
        bar.input.value = "ship it"
        await pilot.press("enter")
        await pilot.pause(delay=0.3)

        assert "Done from TUI." in "\n".join(assistant_contents(app))


@pytest.mark.asyncio
async def test_tui_renders_tool_card_result(tmp_path):
    from pico.tui.app import PicoTuiApp
    from pico.tui.widgets import InputBar, ToolCard

    agent = build_agent(
        tmp_path,
        [
            '<tool name="write_file" path="notes/result.txt"><content>ok\n</content></tool>',
            "<final>Wrote it.</final>",
        ],
    )
    app = PicoTuiApp(agent)

    async with app.run_test() as pilot:
        bar = app.query_one(InputBar)
        bar.input.value = "write a file"
        await pilot.press("enter")
        await pilot.pause(delay=0.5)

        cards = list(app.query(ToolCard))
        assert cards
        assert cards[-1].status == "success"
        assert (tmp_path / "notes" / "result.txt").read_text(encoding="utf-8") == "ok\n"


@pytest.mark.asyncio
async def test_tui_approval_prompt_controls_risky_tool(tmp_path):
    from pico.tui.app import PicoTuiApp
    from pico.tui.widgets import ConfirmPrompt, InputBar

    agent = build_agent(
        tmp_path,
        [
            '<tool name="write_file" path="notes/result.txt"><content>ok\n</content></tool>',
            "<final>Wrote it.</final>",
        ],
        approval_policy="ask",
    )
    app = PicoTuiApp(agent)

    async with app.run_test() as pilot:
        bar = app.query_one(InputBar)
        bar.input.value = "write a file"
        await pilot.press("enter")
        await pilot.pause(delay=0.2)

        assert app.query_one(ConfirmPrompt)

        await pilot.press("right")
        await pilot.press("enter")
        await pilot.pause(delay=0.5)

        assert "Wrote it." in "\n".join(assistant_contents(app))
        assert (tmp_path / "notes" / "result.txt").read_text(encoding="utf-8") == "ok\n"
