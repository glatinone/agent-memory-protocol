"""LangChain integration for AMP.

`AMPMemory` is a `BaseChatMessageHistory` backed by an AMP server, so a
LangChain chain can persist conversation turns as AMP memory cells and read
them back.

History note: this used to subclass `langchain_core.memory.BaseMemory`. That
class was removed in langchain-core 1.0, so importing this module still
"succeeded" (the import sat inside a try/except) while instantiating
`AMPMemory` raised `ImportError: langchain-core is required` even with
langchain-core installed. The guard now checks the class it actually needs, so
the failure mode cannot repeat silently, and the test suite covers it.
"""

from __future__ import annotations

import logging
from typing import Any

from amp_client.client import AMPClient

try:
    from langchain_core.chat_history import BaseChatMessageHistory
    from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

    HAS_LANGCHAIN = True
except ImportError:  # pragma: no cover - exercised only without langchain-core
    HAS_LANGCHAIN = False

    class BaseChatMessageHistory:  # type: ignore[no-redef]
        """Placeholder so the module imports without langchain-core installed."""

    class BaseMessage:  # type: ignore[no-redef]
        """Placeholder, see above."""

    class AIMessage(BaseMessage):  # type: ignore[no-redef]
        """Placeholder, see above."""

    class HumanMessage(BaseMessage):  # type: ignore[no-redef]
        """Placeholder, see above."""

logger = logging.getLogger(__name__)

_HUMAN_PREFIX = "Human: "
_AI_PREFIX = "AI: "


class AMPMemory(BaseChatMessageHistory):
    """Conversation memory for LangChain, stored as AMP episodic cells.

    Each turn is written as one or two episodic memory cells (a `Human:` cell
    and an `AI:` cell), and loading history reads them back in creation order.

    Usage::

        memory = AMPMemory(client=client, owner_id="user-123")
        memory.add_user_message("I prefer dark mode")
        memory.add_ai_message("Noted.")
        for message in memory.messages:
            print(message.type, message.content)
    """

    def __init__(
        self,
        client: AMPClient,
        owner_id: str,
        memory_key: str = "history",
        return_messages: bool = False,
        session_id: str | None = None,
        **kwargs: Any,
    ) -> None:
        if not HAS_LANGCHAIN:
            raise ImportError(
                "langchain-core is required to use AMPMemory. "
                "Install it with: pip install 'amp-client[langchain]'"
            )
        # BaseChatMessageHistory is a pydantic model in langchain-core, so
        # attributes have to be assigned through it rather than on self.
        super().__init__(**kwargs)
        self.client = client
        self.owner_id = owner_id
        self.memory_key = memory_key
        self.return_messages = return_messages
        self.session_id = session_id

    # -- BaseChatMessageHistory interface ---------------------------------

    @property
    def messages(self) -> list[BaseMessage]:  # type: ignore[override]
        """Return stored conversation, oldest first, as LangChain messages."""
        messages: list[BaseMessage] = []
        for cell in self._load_cells():
            text = cell.get("content", {}).get("text", "")
            if text.startswith(_AI_PREFIX):
                messages.append(AIMessage(content=text[len(_AI_PREFIX):]))
            elif text.startswith(_HUMAN_PREFIX):
                messages.append(HumanMessage(content=text[len(_HUMAN_PREFIX):]))
            else:
                # Cells written before the prefixes existed, or by another
                # agent, are treated as human input rather than dropped.
                messages.append(HumanMessage(content=text))
        return messages

    def add_message(self, message: BaseMessage) -> None:
        """Persist a single message."""
        prefix = _AI_PREFIX if message.type == "ai" else _HUMAN_PREFIX
        self.client.remember(
            content=f"{prefix}{message.content}",
            owner_id=self.owner_id,
            type="episodic",
        )

    def clear(self) -> None:
        """Forget every memory cell for this owner."""
        try:
            for cell in self.client.list_memories(owner_id=self.owner_id, limit=1000):
                memory_id = cell.get("id")
                if memory_id:
                    self.client.forget(memory_id)
        except Exception as exc:  # noqa: BLE001 - clear() must not raise mid-chain
            logger.error("Failed to clear memories for owner %s: %s", self.owner_id, exc)

    # -- Chain-facing conveniences ----------------------------------------

    @property
    def memory_variables(self) -> list[str]:
        """Keys this memory injects into chain inputs."""
        return [self.memory_key]

    def load_memory_variables(self, inputs: dict[str, Any]) -> dict[str, Any]:
        """Return history as messages, or as a joined string."""
        messages = self.messages
        if self.return_messages:
            return {self.memory_key: messages}
        history = "\n".join(
            f"{_HUMAN_PREFIX}{m.content}"
            if isinstance(m, HumanMessage)
            else f"{_AI_PREFIX}{m.content}"
            for m in messages
        )
        return {self.memory_key: history}

    def save_context(self, inputs: dict[str, Any], outputs: dict[str, Any]) -> None:
        """Store one turn's input and output."""
        input_text, output_text = self._get_input_output_text(inputs, outputs)
        if input_text:
            self.add_message(HumanMessage(content=input_text))
        if output_text:
            self.add_message(AIMessage(content=output_text))

    # -- Internals ---------------------------------------------------------

    def _load_cells(self) -> list[dict[str, Any]]:
        try:
            cells = self.client.list_memories(
                owner_id=self.owner_id, type="episodic", limit=100
            )
        except Exception as exc:  # noqa: BLE001 - a failing store should not kill the chain
            logger.error("Failed to load memories from AMP: %s", exc)
            return []

        # ISO 8601 sorts lexicographically, so a string sort is a time sort.
        def created_at(cell: dict[str, Any]) -> str:
            value = cell.get("lifecycle", {}).get("created_at") or ""
            return value if isinstance(value, str) else value.isoformat()

        return sorted(cells, key=created_at)

    @staticmethod
    def _get_input_output_text(
        inputs: dict[str, Any], outputs: dict[str, Any]
    ) -> tuple[str, str]:
        """Pull input/output text out of a chain's context dicts."""

        def pick(source: dict[str, Any], keys: list[str]) -> str:
            if not source:
                return ""
            if len(source) == 1:
                return str(next(iter(source.values())))
            for key in keys:
                if key in source:
                    return str(source[key])
            return str(next(iter(source.values())))

        return (
            pick(inputs, ["input", "query", "question"]),
            pick(outputs, ["output", "response", "answer"]),
        )
