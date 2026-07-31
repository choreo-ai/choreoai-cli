"""Shared offline fakes for tests (no API key / network)."""

from __future__ import annotations

from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult


class FakeChatModel(BaseChatModel):
    """Deterministic BaseChatModel stub for offline tool-loop tests.

    Returns canned ``AIMessage`` values in order. ``bind_tools`` returns self
    so the agent loop never hits a network client.
    """

    responses: list[AIMessage] = []
    call_count: int = 0

    @property
    def _llm_type(self) -> str:
        return "fake-chat-model"

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        if not self.responses:
            msg = AIMessage(content="empty-fake")
        elif self.call_count >= len(self.responses):
            msg = self.responses[-1]
        else:
            msg = self.responses[self.call_count]
        self.call_count += 1
        return ChatResult(generations=[ChatGeneration(message=msg)])

    def bind_tools(self, tools: Any, **kwargs: Any) -> FakeChatModel:
        return self
