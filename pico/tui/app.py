from __future__ import annotations

import asyncio
import threading
from functools import partial

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.events import Key

from ..cli import HELP_DETAILS, handle_repl_command
from .widgets import ChatLog, ConfirmPrompt, InputBar, StatusBar, ThinkingIndicator, ToolCard, WelcomeBanner, format_tool_args


PICO_TUI_CSS = """
Screen {
    layout: vertical;
    background: #0f1117;
}
"""


class PicoTuiApp(App):
    """Textual shell for the existing Pico runtime.

    The TUI is deliberately a presentation layer: CLI argument parsing and agent
    construction still live in `pico.cli`, while turns are driven through the
    same `Engine.run_turn()` generator that powers the plain REPL.
    """

    CSS = PICO_TUI_CSS
    BINDINGS = [
        Binding("enter", "submit_input", "Send", priority=True, show=False),
        Binding("ctrl+l", "clear_screen", "Clear"),
        Binding("ctrl+q", "quit", "Quit"),
    ]

    def __init__(self, agent, **kwargs) -> None:
        super().__init__(**kwargs)
        self.agent = agent
        self._turn_count = 0
        self._running_tool_cards: list[ToolCard] = []
        self._confirm_prompt: ConfirmPrompt | None = None
        self._confirm_decision: tuple[threading.Event, dict] | None = None
        self._previous_approve = getattr(agent, "approve", None)
        self.agent.approve = self._approval_callback

    def compose(self) -> ComposeResult:
        yield WelcomeBanner(
            model_name=str(getattr(self.agent.model_client, "model", "")),
            cwd=str(getattr(self.agent, "root", "")),
            approval=str(getattr(self.agent, "approval_policy", "")),
        )
        yield ChatLog()
        yield ThinkingIndicator()
        yield StatusBar()
        yield InputBar()

    def on_mount(self) -> None:
        self.query_one(StatusBar).update_agent(self.agent)
        self.query_one(InputBar).focus_input()

    def on_unmount(self) -> None:
        if self._previous_approve is not None:
            self.agent.approve = self._previous_approve

    def action_clear_screen(self) -> None:
        self.query_one(ChatLog).clear_messages()

    def action_submit_input(self) -> None:
        if self._confirm_prompt is not None:
            self._resolve_confirm(self._confirm_prompt.selected)
            return
        bar = self.query_one(InputBar)
        text = bar.input.value.strip()
        if not text or bar.input.disabled:
            return
        bar.history.append(text)
        bar.history_index = len(bar.history)
        bar.input.value = ""
        if text.startswith("/"):
            self.query_one(ChatLog).add_message("user", text)
            self._handle_command(text)
            return
        self.query_one(ChatLog).add_message("user", text)
        self._run_agent(text)

    def on_key(self, event: Key) -> None:
        if self._confirm_prompt is not None:
            if event.key in {"y", "right"}:
                self._confirm_prompt.select_allow()
                event.prevent_default()
            elif event.key in {"n", "left"}:
                self._confirm_prompt.select_deny()
                event.prevent_default()
            elif event.key == "enter":
                self._resolve_confirm(self._confirm_prompt.selected)
                event.prevent_default()
            elif event.key == "escape":
                self._resolve_confirm(False)
                event.prevent_default()
            return
        bar = self.query_one(InputBar)
        if event.key == "up":
            bar.history_prev()
            event.prevent_default()
        elif event.key == "down":
            bar.history_next()
            event.prevent_default()

    def _handle_command(self, text: str) -> None:
        handled, should_exit, output = handle_repl_command(self.agent, text)
        if should_exit:
            self.exit()
            return
        if handled:
            self.query_one(ChatLog).add_message("assistant", output)
            self.query_one(StatusBar).update_agent(self.agent)
            return
        self.query_one(ChatLog).add_message("assistant", f"Unknown command. Use /help.\n\n{HELP_DETAILS}")

    def _run_agent(self, text: str) -> None:
        self.query_one(InputBar).set_busy(True)
        self.query_one(ThinkingIndicator).show()
        self._thinking_timer = self.set_interval(0.15, self.query_one(ThinkingIndicator).advance)
        asyncio.create_task(self._agent_task(text))

    async def _agent_task(self, text: str) -> None:
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(None, partial(self._drive_turn, text))
        except Exception as exc:
            self.query_one(ChatLog).add_message("assistant", f"[Error] {exc}")
        finally:
            self._stop_thinking()
            self.query_one(InputBar).set_busy(False)
            self.query_one(InputBar).focus_input()
            self._turn_count += 1
            status = self.query_one(StatusBar)
            status.update_turns(self._turn_count)
            status.update_agent(self.agent)
            usage = (getattr(self.agent, "last_prompt_metadata", {}) or {}).get("context_usage") or {}
            status.update_context_usage(usage)

    def _drive_turn(self, text: str) -> None:
        for event in self.agent.engine.run_turn(text):
            try:
                self.call_from_thread(self._handle_runtime_event, dict(event))
            except RuntimeError:
                return

    def _handle_runtime_event(self, event: dict) -> None:
        event_type = str(event.get("type", ""))
        if event_type == "model_requested":
            attempts = event.get("attempts", 0)
            tool_steps = event.get("tool_steps", 0)
            self.query_one(ThinkingIndicator).set_detail(f"model request {attempts}, tools {tool_steps}")
            return
        if event_type == "model_parsed":
            kind = event.get("kind", "")
            self.query_one(ThinkingIndicator).set_detail(f"model returned {kind}")
            return
        if event_type == "tool_call":
            name = str(event.get("name", ""))
            args = event.get("args") if isinstance(event.get("args"), dict) else {}
            self.query_one(ThinkingIndicator).set_detail(f"running {name}")
            card = self.query_one(ChatLog).add_tool_call(name, args)
            self._running_tool_cards.append(card)
            return
        if event_type == "tool_result":
            self._finish_tool_card(event)
            self.query_one(ThinkingIndicator).set_detail("thinking after tool")
            return
        if event_type in {"retry", "runtime_notice", "final", "stop"}:
            self.query_one(ChatLog).add_message("assistant", str(event.get("content", "")))
            return

    def _finish_tool_card(self, event: dict) -> None:
        name = str(event.get("name", ""))
        card = None
        for candidate in reversed(self._running_tool_cards):
            if candidate.tool_name == name and candidate.status == "running":
                card = candidate
                break
        if card is None:
            card = self.query_one(ChatLog).add_tool_call(name, {})
        metadata = event.get("metadata") if isinstance(event.get("metadata"), dict) else {}
        content = str(event.get("content", ""))
        status = str(metadata.get("tool_status", "ok") or "ok")
        if status in {"error", "rejected", "partial_success"}:
            card.set_error(content)
        else:
            card.set_success(content)

    def _stop_thinking(self) -> None:
        timer = getattr(self, "_thinking_timer", None)
        if timer is not None:
            timer.stop()
            self._thinking_timer = None
        self.query_one(ThinkingIndicator).hide()

    def _approval_callback(self, name: str, args: dict) -> bool:
        event = threading.Event()
        decision = {"approved": False}
        try:
            self.call_from_thread(self._show_confirm, name, args, event, decision)
        except RuntimeError:
            return False
        event.wait()
        return bool(decision.get("approved", False))

    def _show_confirm(self, name: str, args: dict, event: threading.Event, decision: dict) -> None:
        prompt = ConfirmPrompt(name, format_tool_args(name, args))
        self._confirm_prompt = prompt
        self._confirm_decision = (event, decision)
        chat = self.query_one(ChatLog)
        chat.mount(prompt)
        chat.call_after_refresh(chat.scroll_end, animate=False)

    def _resolve_confirm(self, approved: bool) -> None:
        if self._confirm_decision is None:
            return
        event, decision = self._confirm_decision
        decision["approved"] = bool(approved)
        event.set()
        if self._confirm_prompt is not None:
            self._confirm_prompt.remove()
        self._confirm_prompt = None
        self._confirm_decision = None
