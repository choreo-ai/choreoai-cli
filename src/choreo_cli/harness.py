"""Coding-agent harness: LLMAgent + tools + Budget/Trace middleware."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool

from choreo.agents import LLMAgent
from choreo.core import (
    BudgetMiddleware,
    InMemoryRunContext,
    ListSubscriber,
    OnionMiddlewareStack,
    SimpleEventEmitter,
    Subscriber,
    TraceMiddleware,
)
from choreo.reliability import BudgetDimensions, InMemoryBudget

from choreo_cli.tools import ShellApprovalPolicy, default_tools

CODING_SYSTEM_PROMPT = """\
You are a careful coding assistant working in a local project directory.

You have tools: read_file, write_file, list_dir, run_shell.
- Prefer reading and listing before writing.
- Make small, focused changes.
- run_shell may require user approval; keep commands safe and minimal.
- Explain what you did briefly when finished.
- Stay inside the project unless the user asks otherwise.
"""

DEFAULT_STEP_BUDGET = 20.0


@dataclass
class RunResult:
    """Outcome of one harness run (agent turn)."""

    output: Any
    budget_snapshot: Any
    events: list[Any] = field(default_factory=list)
    run_id: str = ""


@dataclass
class CodingHarness:
    """Wires choreoai LLMAgent with budget/trace middleware and coding tools.

    Session state (shared across REPL turns):
    - One ``InMemoryRunContext`` budget ledger (cumulative cap)
    - Optional ``ShellApprovalPolicy`` (always-allow / deny patterns)
    """

    agent: LLMAgent
    budget: InMemoryBudget
    emitter: SimpleEventEmitter
    subscriber: ListSubscriber
    cwd: Path
    max_steps: int = 10
    step_budget: float = DEFAULT_STEP_BUDGET
    session_context: InMemoryRunContext | None = None
    shell_policy: ShellApprovalPolicy | None = None

    @classmethod
    def create(
        cls,
        *,
        model: BaseChatModel,
        cwd: Path | None = None,
        tools: list[BaseTool] | None = None,
        auto: bool = False,
        confirm: Callable[[str], bool] | None = None,
        instructions: str = CODING_SYSTEM_PROMPT,
        max_steps: int = 10,
        step_budget: float = DEFAULT_STEP_BUDGET,
        name: str = "coding_agent",
    ) -> CodingHarness:
        root = (cwd or Path.cwd()).resolve()
        emitter = SimpleEventEmitter()
        subscriber = ListSubscriber(name="harness_trace")
        emitter.subscribe(subscriber)

        shell_policy: ShellApprovalPolicy | None = None
        if confirm is None and not auto:
            shell_policy = ShellApprovalPolicy()
            confirm = shell_policy
        elif isinstance(confirm, ShellApprovalPolicy):
            shell_policy = confirm

        tool_list = tools if tools is not None else default_tools(
            root, auto=auto, confirm=confirm
        )
        agent = LLMAgent(
            name=name,
            instructions=instructions,
            tools=tool_list,
            model=model,
            max_steps=max_steps,
            emitter=emitter,
        )
        budget = InMemoryBudget(caps={BudgetDimensions.STEPS.value: step_budget})
        harness = cls(
            agent=agent,
            budget=budget,
            emitter=emitter,
            subscriber=subscriber,
            cwd=root,
            max_steps=max_steps,
            step_budget=step_budget,
            shell_policy=shell_policy,
        )
        harness.reset_session()
        return harness

    def _new_session_context(self) -> InMemoryRunContext:
        return InMemoryRunContext(
            budget_ledger={
                "caps": {BudgetDimensions.STEPS.value: self.step_budget},
                "consumed": {},
                "labels": {},
            }
        )

    def reset_trace(self) -> None:
        """Clear collected events (e.g. between REPL turns)."""
        self.subscriber.events.clear()

    def reset_session(self) -> None:
        """Clear session budget ledger, trace, and shell approval session state."""
        self.reset_trace()
        self.session_context = self._new_session_context()
        # Fresh internal budget (context ledger is authoritative when present).
        self.budget = InMemoryBudget(caps={BudgetDimensions.STEPS.value: self.step_budget})
        if self.shell_policy is not None:
            self.shell_policy.reset()

    def ensure_session_context(self) -> InMemoryRunContext:
        """Return the shared session RunContext, creating one if needed."""
        if self.session_context is None:
            self.session_context = self._new_session_context()
        return self.session_context

    def add_subscriber(self, subscriber: Subscriber) -> None:
        """Subscribe an extra event consumer (e.g. live REPL streamer)."""
        self.emitter.subscribe(subscriber)

    def budget_summary(self, context: InMemoryRunContext | None = None) -> str:
        ctx = context if context is not None else self.session_context
        snap = self.budget.snapshot(context=ctx)
        parts: list[str] = []
        for dim, cap in snap.caps.items():
            used = snap.consumed.get(dim, 0.0)
            parts.append(f"{dim}: {used:g}/{cap:g}")
        return ", ".join(parts) if parts else "no caps"

    def trace_summary(self) -> str:
        events = self.subscriber.events
        if not events:
            return "no events"
        counts: dict[str, int] = {}
        for e in events:
            counts[e.type] = counts.get(e.type, 0) + 1
        bits = [f"{k}={v}" for k, v in sorted(counts.items())]
        tools = [e for e in events if getattr(e, "type", None) == "tool_called"]
        if tools:
            names = ", ".join(getattr(e, "tool_name", "?") for e in tools)
            bits.append(f"tools=[{names}]")
        return "; ".join(bits)

    async def arun(self, instruction: str) -> RunResult:
        """Run one agent turn under Budget + Trace middleware.

        Uses the **session** RunContext ledger so budget consumption accumulates
        across REPL turns until ``reset_session`` / ``/reset``.
        """
        self.reset_trace()
        context = self.ensure_session_context()

        async def run_agent(value: object) -> object:
            return await self.agent.ainvoke(
                {"input": value, "run_context": context}
            )

        stack = OnionMiddlewareStack(
            [
                TraceMiddleware(emitter=self.emitter, node_id="harness"),
                BudgetMiddleware(
                    self.budget,
                    amounts={BudgetDimensions.STEPS.value: 1.0},
                ),
            ],
            node=run_agent,
        )
        result = await stack.ainvoke(instruction, context=context)

        output: Any = result
        if isinstance(result, dict):
            output = result.get("output", result.get("value", result))

        return RunResult(
            output=output,
            budget_snapshot=self.budget.snapshot(context=context),
            events=list(self.subscriber.events),
            run_id=context.run_id,
        )

    def run(self, instruction: str) -> RunResult:
        """Sync wrapper around ``arun`` (not usable inside a running event loop)."""
        import asyncio

        return asyncio.run(self.arun(instruction))
