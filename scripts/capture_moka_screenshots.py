"""Capture deterministic Moka TUI screenshots with Textual's SVG exporter."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
from types import SimpleNamespace

from pico.tui.app import PicoTuiApp
from pico.tui.widgets import ChatLog, InputBar, WelcomeBanner


class _ScreenshotEngine:
    def drain_worker_notifications(self) -> list[str]:
        return []


def _agent() -> SimpleNamespace:
    return SimpleNamespace(
        model_client=SimpleNamespace(model="gpt-5.4"),
        root=Path.cwd().resolve(),
        approval_policy="ask",
        runtime_mode="default",
        session={"id": "moka-demo"},
        engine=_ScreenshotEngine(),
        approve=None,
        ask_user_callback=None,
    )


async def _capture(output_dir: Path, filename: str, scene: str) -> None:
    app = PicoTuiApp(_agent())
    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()
        chat = app.query_one(ChatLog)
        bar = app.query_one(InputBar)

        if scene != "intro":
            app.query_one(WelcomeBanner).add_class("hidden")

        if scene == "tools":
            chat.add_message("user", "Inspect this project and identify improvements")
            chat.add_message(
                "assistant",
                "I will inspect the project structure and runtime entry points first.",
            )
            first = chat.add_tool_call("list_files", {"path": "."})
            second = chat.add_tool_call(
                "read_file", {"path": "pico/core/runtime.py"}
            )
            await pilot.pause()
            first.set_success("README.md\npico/\ntests/\nscripts/")
            second.set_success("Runtime entry points inspected.")
        elif scene == "skills-help":
            chat.add_message("user", "/help")
            chat.add_message(
                "assistant",
                "## Commands\n\n"
                "- `/skills` list reusable workflows\n"
                "- `/plan <topic>` enter plan mode\n"
                "- `/review` inspect current changes\n"
                "- `/test <target>` run focused verification\n"
                "- `/memory` inspect durable project memory",
            )
        elif scene == "memory-skills":
            chat.add_message("user", "/memory")
            chat.add_message(
                "assistant",
                "## Durable memory\n\n"
                "- Project conventions: preserve runtime evidence\n"
                "- Git workflow: small, truthful commits\n"
                "- Product identity: Moka UI with pico-compatible core\n\n"
                "Use `/skills` to run a reusable project workflow.",
            )
        elif scene == "latest":
            bar.input.value = "/"
            bar.update_slash_suggestions("/")
            bar.focus_input()

        await pilot.pause()
        app.save_screenshot(filename=filename, path=str(output_dir))


async def capture_all(output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    scenes = {
        "moka-tui-intro.svg": "intro",
        "moka-tui-tools.svg": "tools",
        "moka-tui-skills-help.svg": "skills-help",
        "moka-tui-memory-skills.svg": "memory-skills",
        "moka-tui-latest.svg": "latest",
    }
    for filename, scene in scenes.items():
        await _capture(output_dir, filename, scene)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir", default="assets/screenshots", help="Screenshot output directory."
    )
    args = parser.parse_args()
    asyncio.run(capture_all(Path(args.output_dir).resolve()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
