"""Tests for the LangChain integration.

These exist because the integration silently broke: it subclassed
`langchain_core.memory.BaseMemory`, which langchain-core 1.0 removed. The
import sat in a try/except, so the module imported fine and only failed when
`AMPMemory(...)` was constructed, with a message blaming a missing
langchain-core that was in fact installed. None of that was covered by a test.

The first test below is the regression guard for exactly that: it asserts the
base class exists, so a future removal fails here instead of in a user's app.

The AMP client is mocked. These test the integration's own logic, not the
server; `python/tests/test_client.py` and the server suite cover the HTTP layer.
"""

from __future__ import annotations

from typing import Any

import pytest

pytest.importorskip("langchain_core")  # skip cleanly when the extra is absent

from langchain_core.chat_history import BaseChatMessageHistory  # noqa: E402
from langchain_core.messages import AIMessage, HumanMessage  # noqa: E402

from amp_client.integrations.langchain import AMPMemory  # noqa: E402


class FakeAMPClient:
    """Stands in for AMPClient, storing cells in a list.

    Mirrors the real client's surface for the calls the integration makes, and
    assigns created_at in insertion order so ordering assertions are meaningful.
    """

    def __init__(self) -> None:
        self.cells: list[dict[str, Any]] = []
        self._counter = 0
        self.fail_on_list = False

    def remember(self, content: str, owner_id: str, type: str = "semantic", **_: Any) -> dict:
        self._counter += 1
        cell = {
            "id": f"mem_test_{self._counter}",
            # Zero-padded so lexical sort matches insertion order.
            "lifecycle": {"created_at": f"2026-10-03T00:00:{self._counter:02d}Z"},
            "type": type,
            "content": {"text": content},
            "identity": {"owner_id": owner_id},
            "scoring": {"importance": 0.5},
        }
        self.cells.append(cell)
        return cell

    def list_memories(self, owner_id: str, type: str | None = None, limit: int = 20) -> list[dict]:
        if self.fail_on_list:
            raise RuntimeError("storage unavailable")
        return [
            c
            for c in self.cells
            if c["identity"]["owner_id"] == owner_id
            and (type is None or c["type"] == type)
        ][:limit]

    def forget(self, memory_id: str) -> bool:
        self.cells = [c for c in self.cells if c["id"] != memory_id]
        return True


def make_memory(**kwargs: Any) -> tuple[AMPMemory, FakeAMPClient]:
    client = FakeAMPClient()
    memory = AMPMemory(client=client, owner_id="user-1", **kwargs)
    return memory, client


# ---------------------------------------------------------------------------
# The regression this file was written for
# ---------------------------------------------------------------------------


def test_memory_is_a_chat_message_history():
    """The base class must exist and be the one langchain-core actually exports.

    A previous version subclassed `langchain_core.memory.BaseMemory`, removed in
    langchain-core 1.0. This assertion fails loudly if the base moves again.
    """
    assert issubclass(AMPMemory, BaseChatMessageHistory)


def test_construction_does_not_raise():
    """Constructing the memory must not raise when langchain-core is installed."""
    memory, _ = make_memory()
    assert memory.owner_id == "user-1"


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------


def test_add_message_stores_a_prefixed_cell():
    memory, client = make_memory()
    memory.add_message(HumanMessage(content="I prefer dark mode"))

    assert len(client.cells) == 1
    assert client.cells[0]["content"]["text"] == "Human: I prefer dark mode"
    assert client.cells[0]["type"] == "episodic"


def test_add_ai_message_uses_ai_prefix():
    memory, client = make_memory()
    memory.add_message(AIMessage(content="Noted."))

    assert client.cells[0]["content"]["text"] == "AI: Noted."


def test_save_context_writes_both_turns():
    memory, client = make_memory()
    memory.save_context({"input": "hello"}, {"output": "hi"})

    texts = [c["content"]["text"] for c in client.cells]
    assert texts == ["Human: hello", "AI: hi"]


def test_save_context_picks_known_keys():
    """With multiple keys, the well-known ones win over insertion order."""
    memory, client = make_memory()
    memory.save_context(
        {"unrelated": "x", "question": "the real question"},
        {"metadata": "y", "answer": "the real answer"},
    )

    texts = [c["content"]["text"] for c in client.cells]
    assert texts == ["Human: the real question", "AI: the real answer"]


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


def test_messages_round_trips_types_and_order():
    memory, _ = make_memory()
    memory.add_message(HumanMessage(content="one"))
    memory.add_message(AIMessage(content="two"))

    messages = memory.messages
    assert [m.type for m in messages] == ["human", "ai"]
    assert [m.content for m in messages] == ["one", "two"]


def test_messages_sorted_by_created_at_not_list_order():
    """Ordering comes from the server's created_at, not the local list."""
    memory, client = make_memory()
    memory.add_message(HumanMessage(content="first"))
    memory.add_message(AIMessage(content="second"))
    client.cells.reverse()

    assert [m.content for m in memory.messages] == ["first", "second"]


def test_unprefixed_cell_is_read_as_human():
    """Cells written by another agent, without a prefix, are not dropped."""
    memory, client = make_memory()
    client.cells.append(
        {
            "id": "mem_external",
            "lifecycle": {"created_at": "2026-10-03T00:00:00Z"},
            "type": "episodic",
            "content": {"text": "written elsewhere"},
            "identity": {"owner_id": "user-1"},
        }
    )
    messages = memory.messages
    assert len(messages) == 1
    assert messages[0].type == "human"
    assert messages[0].content == "written elsewhere"


def test_load_memory_variables_returns_string_by_default():
    memory, _ = make_memory()
    memory.save_context({"input": "hello"}, {"output": "hi"})

    result = memory.load_memory_variables({})
    assert result["history"] == "Human: hello\nAI: hi"


def test_load_memory_variables_returns_messages_when_asked():
    memory, _ = make_memory(return_messages=True)
    memory.save_context({"input": "hello"}, {"output": "hi"})

    result = memory.load_memory_variables({})
    assert [m.type for m in result["history"]] == ["human", "ai"]


def test_memory_variables_exposes_the_configured_key():
    memory, _ = make_memory(memory_key="chat_history")
    assert memory.memory_variables == ["chat_history"]


# ---------------------------------------------------------------------------
# Failure handling
# ---------------------------------------------------------------------------


def test_load_degrades_to_empty_when_storage_fails():
    """A broken store must not raise into the middle of a chain run."""
    memory, client = make_memory()
    client.fail_on_list = True

    assert memory.messages == []
    assert memory.load_memory_variables({}) == {"history": ""}


def test_clear_forgets_every_cell():
    memory, client = make_memory()
    memory.save_context({"input": "a"}, {"output": "b"})
    assert len(client.cells) == 2

    memory.clear()
    assert client.cells == []


def test_clear_does_not_raise_when_storage_fails():
    memory, client = make_memory()
    client.fail_on_list = True
    memory.clear()  # must not raise
