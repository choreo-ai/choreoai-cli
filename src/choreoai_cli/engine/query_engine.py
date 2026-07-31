"""QueryEngine: per-session object wrapping choreoai LLMAgent + budget/trace.

Exposes ``submit(prompt)`` as an async generator of typed turn events that the
UI can subscribe to. The LLM tool loop itself remains in choreoai; this wraps
and organizes it (Budget / Trace middleware, permission context, turn outcomes).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator, Callable

from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool

from choreoai.agents import LLMAgent
from choreoai.core import (
    BudgetMiddleware,
    InMemoryRunContext,
    ListSubscriber,
    OnionMiddlewareStack,
    SimpleEventEmitter,
    Subscriber,
    TraceMiddleware,
)
from choreoai.core.events import Event
from choreoai.reliability import BudgetDimensions, BudgetExhausted, InMemoryBudget

from choreoai_cli.engine.events import (
    TurnEvent,
    TurnFinished,
    TurnStarted,
    TurnStats,
    adapt_choreoai_event,
)
from choreoai_cli.engine.turn import TurnOutcome
from choreoai_cli.permissions.approval import ShellApprovalPolicy
from choreoai_cli.permissions.context import PermissionContext
from choreoai_cli.tools import get_default_tools

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
    outcome: TurnOutcome = TurnOutcome.COMPLETED


@dataclass
class CodingHarness:
    """Wires choreoai LLMAgent with budget/trace middleware and coding tools.

    Session state (shared across REPL turns):
    - One ``InMemoryRunContext`` budget ledger (cumulative cap)
    - Optional ``ShellApprovalPolicy`` (always-allow / deny patterns)
    - ``PermissionContext`` for 3-tier allow/deny/ask decisions
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
    permission_context: PermissionContext | None = None

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
        permission_context: PermissionContext | None = None,
    ) -> CodingHarness:
        root = (cwd or Path.cwd()).resolve()
        emitter = SimpleEventEmitter()
        subscriber = ListSubscriber(name="harness_trace")
        emitter.subscribe(subscriber)

        perm = permission_context or PermissionContext.from_auto(auto)

        shell_policy: ShellApprovalPolicy | None = None
        if confirm is None and not auto:
            shell_policy = ShellApprovalPolicy(context=perm)
            confirm = shell_policy
        elif isinstance(confirm, ShellApprovalPolicy):
            shell_policy = confirm
            if shell_policy.context is None:
                shell_policy.context = perm

        tool_list = (
            tools
            if tools is not None
            else get_default_tools(
                root,
                auto=auto,
                confirm=confirm,
                permission_context=perm,
            )
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
            permission_context=perm,
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
        self.budget = InMemoryBudget(
            caps={BudgetDimensions.STEPS.value: self.step_budget}
        )
        if self.shell_policy is not None:
            self.shell_policy.reset()
        if self.permission_context is not None:
            self.permission_context.reset_session()

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
            outcome=TurnOutcome.COMPLETED,
        )

    def run(self, instruction: str) -> RunResult:
        """Sync wrapper around ``arun`` (not usable inside a running event loop)."""
        import asyncio

        return asyncio.run(self.arun(instruction))


class _CollectingBridge(Subscriber):
    """Subscriber that adapts choreoai events into typed TurnEvents."""

    name = "query_engine_bridge"

    def __init__(self, stats: TurnStats) -> None:
        self.stats = stats
        self.events: list[TurnEvent] = []

    async def on_event(self, event: Event) -> None:
        adapted = adapt_choreoai_event(event, stats=self.stats)
        if adapted is not None:
            self.events.append(adapted)


class QueryEngine:
    """Per-session query engine: ``submit(prompt)`` yields typed turn events.

    Wraps :class:`CodingHarness` (LLMAgent + Budget/Trace). One instance is
    created per CLI session and reused across REPL turns.
    """

    def __init__(self, harness: CodingHarness) -> None:
        self.harness = harness
        self.turn_stats = TurnStats()
        self.last_outcome: TurnOutcome | None = None

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
        permission_context: PermissionContext | None = None,
    ) -> QueryEngine:
        harness = CodingHarness.create(
            model=model,
            cwd=cwd,
            tools=tools,
            auto=auto,
            confirm=confirm,
            instructions=instructions,
            max_steps=max_steps,
            step_budget=step_budget,
            name=name,
            permission_context=permission_context,
        )
        return cls(harness)

    # --- session surface (delegates so REPL can treat engine like harness) ---

    @property
    def cwd(self) -> Path:
        return self.harness.cwd

    @property
    def agent(self) -> LLMAgent:
        return self.harness.agent

    @property
    def budget(self) -> InMemoryBudget:
        return self.harness.budget

    @property
    def session_context(self) -> InMemoryRunContext | None:
        return self.harness.session_context

    @property
    def shell_policy(self) -> ShellApprovalPolicy | None:
        return self.harness.shell_policy

    @property
    def permission_context(self) -> PermissionContext | None:
        return self.harness.permission_context

    def add_subscriber(self, subscriber: Subscriber) -> None:
        self.harness.add_subscriber(subscriber)

    def reset_session(self) -> None:
        self.harness.reset_session()
        self.turn_stats.reset()
        self.last_outcome = None

    def reset_trace(self) -> None:
        self.harness.reset_trace()

    def budget_summary(self, context: InMemoryRunContext | None = None) -> str:
        return self.harness.budget_summary(context)

    def trace_summary(self) -> str:
        return self.harness.trace_summary()

    def run(self, instruction: str) -> RunResult:
        return self.harness.run(instruction)

    async def arun(self, instruction: str) -> RunResult:
        return await self.harness.arun(instruction)

    async def submit(self, prompt: str) -> AsyncIterator[TurnEvent]:
        """Run one turn and yield typed events for UI consumers.

        Yields ``TurnStarted``, then adapted tool/llm events collected during
        the run, then ``TurnFinished`` with a named :class:`TurnOutcome`.
        """
        self.turn_stats.reset()
        bridge = _CollectingBridge(self.turn_stats)
        self.harness.add_subscriber(bridge)

        yield TurnStarted(prompt=prompt)

        try:
            result = await self.harness.arun(prompt)
            for ev in bridge.events:
                yield ev
            self.last_outcome = TurnOutcome.COMPLETED
            yield TurnFinished(
                outcome=TurnOutcome.COMPLETED,
                output=result.output,
                run_id=result.run_id,
            )
        except BudgetExhausted as exc:
            for ev in bridge.events:
                yield ev
            self.last_outcome = TurnOutcome.BUDGET_EXCEEDED
            yield TurnFinished(
                outcome=TurnOutcome.BUDGET_EXCEEDED,
                error=str(exc),
            )
        except KeyboardInterrupt:
            self.last_outcome = TurnOutcome.ABORTED
            yield TurnFinished(outcome=TurnOutcome.ABORTED, error="aborted")
        except Exception as exc:
            for ev in bridge.events:
                yield ev
            self.last_outcome = TurnOutcome.ERROR
            yield TurnFinished(outcome=TurnOutcome.ERROR, error=str(exc))
