"""Scripted demo BaseChatModel — realistic multi-step turns without an API key.

Used when ``--demo`` is set or when an interactive session has no
``ANTHROPIC_API_KEY``. Tools still run for real (read_file / list_dir /
safe shell); only the "LLM" side is mocked.
"""

from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Any, Callable

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult


def _last_human_text(messages: list[BaseMessage]) -> str:
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            text = msg.content
            return text if isinstance(text, str) else str(text)
    return "your request"


def _count_ai_messages(messages: list[BaseMessage]) -> int:
    return sum(1 for m in messages if isinstance(m, AIMessage))


def _short_request(text: str, *, limit: int = 60) -> str:
    one = " ".join(text.strip().split())
    if len(one) <= limit:
        return one
    return one[: limit - 1] + "…"


def _pick_readable_file(cwd: Path) -> str:
    """Prefer a real project file so read_file returns genuine content."""
    candidates = (
        "README.md",
        "pyproject.toml",
        "package.json",
        "setup.py",
        "setup.cfg",
        "Cargo.toml",
        "go.mod",
        "hello.txt",
        "LICENSE",
    )
    for name in candidates:
        if (cwd / name).is_file():
            return name
    try:
        for p in sorted(cwd.iterdir()):
            if p.is_file() and p.stat().st_size < 64_000:
                return p.name
    except OSError:
        pass
    return "README.md"


def _safe_shell_command() -> str:
    """Cross-platform, read-only-ish echo for the demo tool card."""
    return 'echo choreoai-demo'


def _final_markdown(request: str, *, scenario: str, files_hint: str) -> str:
    req = _short_request(request)
    if scenario == "shell":
        return (
            f"## Demo walkthrough\n\n"
            f"You asked: **{req}**\n\n"
            f"This is a **scripted demo** (no live model). Here is a sample plan:\n\n"
            f"- Inspect the working tree with `list_dir`\n"
            f"- Run a safe diagnostic shell command\n"
            f"- Summarize next steps for a real agent turn\n\n"
            f"### Example snippet\n\n"
            f"```python\n"
            f"def plan_refactor(module: str) -> list[str]:\n"
            f"    return [\n"
            f"        f\"map call sites in {{module}}\",\n"
            f"        \"extract shared helper\",\n"
            f"        \"add regression tests\",\n"
            f"    ]\n"
            f"```\n\n"
            f"_Switch off demo mode with `ANTHROPIC_API_KEY` set and no `--demo`._"
        )
    if scenario == "deep":
        return (
            f"## Auth / project sketch\n\n"
            f"Request: **{req}**\n\n"
            f"I used tools against **{files_hint}** and the project root. "
            f"A real model would edit files next; demo mode only shows the UI.\n\n"
            f"- Read a project file for context\n"
            f"- List the directory layout\n"
            f"- Run a harmless shell probe\n"
            f"- Return this Markdown answer (heading, list, code block)\n\n"
            f"```python\n"
            f"# illustrative — not applied in demo mode\n"
            f"def authenticate(user: str, token: str) -> bool:\n"
            f"    \"\"\"Validate credentials (demo stub).\"\"\"\n"
            f"    return bool(user and token)\n"
            f"```\n\n"
            f"Footer below shows mock-sensible tokens, tools, budget, and elapsed time."
        )
    # explore (default)
    return (
        f"## Demo answer\n\n"
        f"You said: **{req}**\n\n"
        f"This turn is a **mock agent** so you can see the full UI without an API key:\n\n"
        f"- Tool cards for `read_file` / `list_dir` (real tool results)\n"
        f"- Streamed-feeling step pauses between model/tool phases\n"
        f"- This Markdown answer with a fenced code block\n"
        f"- Turn footer (tokens · cost · tools · budget · time)\n\n"
        f"### Sample code\n\n"
        f"```python\n"
        f"from pathlib import Path\n\n"
        f"def summarize_project(root: Path) -> str:\n"
        f"    files = sorted(p.name for p in root.iterdir() if p.is_file())\n"
        f"    return f\"{{len(files)}} files under {{root}}\"\n"
        f"```\n\n"
        f"File peeked: `{files_hint}`. Try another prompt for a different demo scenario."
    )


# Scenario builders: each returns the AIMessage for the current agent step
# (0-based step = number of prior AIMessages in the conversation).
ScenarioFn = Callable[[list[BaseMessage], Path], AIMessage]


def _scenario_explore(messages: list[BaseMessage], cwd: Path) -> AIMessage:
    step = _count_ai_messages(messages)
    path = _pick_readable_file(cwd)
    request = _last_human_text(messages)
    if step == 0:
        return AIMessage(
            content=f"I'll inspect `{path}` and the project layout for: {_short_request(request)}.",
            tool_calls=[
                {
                    "name": "read_file",
                    "args": {"path": path},
                    "id": "demo_read_1",
                }
            ],
        )
    if step == 1:
        return AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "list_dir",
                    "args": {"path": "."},
                    "id": "demo_list_1",
                }
            ],
        )
    return AIMessage(
        content=_final_markdown(request, scenario="explore", files_hint=path)
    )


def _scenario_shell(messages: list[BaseMessage], cwd: Path) -> AIMessage:
    step = _count_ai_messages(messages)
    request = _last_human_text(messages)
    path = _pick_readable_file(cwd)
    if step == 0:
        return AIMessage(
            content="Listing the workspace, then running a safe shell probe.",
            tool_calls=[
                {
                    "name": "list_dir",
                    "args": {"path": "."},
                    "id": "demo_list_2",
                }
            ],
        )
    if step == 1:
        return AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "run_shell",
                    "args": {"command": _safe_shell_command()},
                    "id": "demo_shell_1",
                }
            ],
        )
    return AIMessage(
        content=_final_markdown(request, scenario="shell", files_hint=path)
    )


def _scenario_deep(messages: list[BaseMessage], cwd: Path) -> AIMessage:
    step = _count_ai_messages(messages)
    path = _pick_readable_file(cwd)
    request = _last_human_text(messages)
    if step == 0:
        return AIMessage(
            content=f"Deep demo: reading `{path}`, listing, then a safe shell command.",
            tool_calls=[
                {
                    "name": "read_file",
                    "args": {"path": path},
                    "id": "demo_read_2",
                }
            ],
        )
    if step == 1:
        return AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "list_dir",
                    "args": {"path": "."},
                    "id": "demo_list_3",
                }
            ],
        )
    if step == 2:
        return AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "run_shell",
                    "args": {"command": _safe_shell_command()},
                    "id": "demo_shell_2",
                }
            ],
        )
    return AIMessage(
        content=_final_markdown(request, scenario="deep", files_hint=path)
    )


_SCENARIOS: list[tuple[str, ScenarioFn]] = [
    ("explore", _scenario_explore),
    ("shell", _scenario_shell),
    ("deep", _scenario_deep),
]


def choose_scenario(prompt: str) -> str:
    """Stable pick among canned scenarios from the user prompt text."""
    digest = hashlib.sha256(prompt.encode("utf-8", errors="replace")).digest()
    idx = digest[0] % len(_SCENARIOS)
    return _SCENARIOS[idx][0]


def _scenario_fn(name: str) -> ScenarioFn:
    for n, fn in _SCENARIOS:
        if n == name:
            return fn
    return _scenario_explore


class DemoChatModel(BaseChatModel):
    """LangChain-compatible scripted model for demo / no-API-key sessions.

    Emits multi-step tool calls then a Markdown final answer. Small delays
    between steps make tool cards feel live without slowing demos much.
    """

    model_name: str = "demo-mock"
    is_demo: bool = True
    cwd: Path = Path(".")
    delay_s: float = 0.12
    # Per-turn usage (drained into the live footer after each agent turn).
    turn_input_tokens: int = 0
    turn_output_tokens: int = 0
    call_count: int = 0
    last_scenario: str = "explore"

    @property
    def _llm_type(self) -> str:
        return "demo-chat-model"

    @property
    def _identifying_params(self) -> dict[str, Any]:
        return {"model_name": self.model_name}

    def bind_tools(self, tools: Any, **kwargs: Any) -> DemoChatModel:
        return self

    def drain_usage(self) -> tuple[int, int]:
        """Return and clear per-turn mock token counters for the footer."""
        inn, out = self.turn_input_tokens, self.turn_output_tokens
        self.turn_input_tokens = 0
        self.turn_output_tokens = 0
        return inn, out

    def _bump_usage(self, message: AIMessage) -> None:
        # Sensible mock numbers so the footer is non-empty and stable-ish.
        content = message.content if isinstance(message.content, str) else ""
        out = max(40, min(800, len(content) // 3 + 60))
        inn = max(120, out * 3 + 80 * (1 + len(getattr(message, "tool_calls", None) or [])))
        self.turn_input_tokens += inn
        self.turn_output_tokens += out

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        if self.delay_s > 0:
            time.sleep(self.delay_s)

        request = _last_human_text(messages)
        # Re-pick scenario only at the start of a tool loop (no prior AI msgs).
        if _count_ai_messages(messages) == 0:
            self.last_scenario = choose_scenario(request)

        fn = _scenario_fn(self.last_scenario)
        root = Path(self.cwd)
        try:
            root = root.resolve()
        except OSError:
            pass
        msg = fn(messages, root)
        self._bump_usage(msg)
        self.call_count += 1
        return ChatResult(generations=[ChatGeneration(message=msg)])


def make_demo_model(
    *,
    cwd: Path | None = None,
    delay_s: float = 0.12,
) -> DemoChatModel:
    """Factory for the demo mock model rooted at ``cwd``."""
    root = (cwd or Path.cwd()).resolve()
    return DemoChatModel(cwd=root, delay_s=delay_s)
