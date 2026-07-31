"""Shared pytest fixtures: fake chat model (offline, no API key)."""

from __future__ import annotations

from pathlib import Path

import pytest
from langchain_core.messages import AIMessage

from fakes import FakeChatModel


@pytest.fixture
def tmp_project(tmp_path: Path) -> Path:
    """A temporary project directory with a sample file."""
    (tmp_path / "hello.txt").write_text("hello world\n", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("print('hi')\n", encoding="utf-8")
    return tmp_path


@pytest.fixture
def fake_final_only() -> FakeChatModel:
    return FakeChatModel(responses=[AIMessage(content="final answer")])


@pytest.fixture
def fake_with_list_dir() -> FakeChatModel:
    """Model that calls list_dir once, then returns a final answer."""
    return FakeChatModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {"name": "list_dir", "args": {"path": "."}, "id": "call_1"}
                ],
            ),
            AIMessage(content="I listed the directory."),
        ]
    )
