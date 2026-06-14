import logging
from typing import Any, Dict, List

try:
    from langchain_core.memory import BaseMemory
    HAS_LANGCHAIN = True
except ImportError:
    # Guard so the module can be imported even if langchain-core is not installed
    class BaseMemory:  # type: ignore
        def __init__(self, *args, **kwargs):
            raise ImportError(
                "langchain-core is required to use AMPMemory. "
                "Install it with: pip install langchain-core"
            )
    HAS_LANGCHAIN = False

from amp_client.client import AMPClient

logger = logging.getLogger(__name__)

class AMPMemory(BaseMemory):
    """LangChain BaseMemory integration with Agent Memory Protocol (AMP)."""
    client: AMPClient
    owner_id: str
    memory_key: str = "history"
    return_messages: bool = False

    def __init__(self, **data: Any):
        if not HAS_LANGCHAIN:
            raise ImportError(
                "langchain-core is required to use AMPMemory. "
                "Install it with: pip install langchain-core"
            )
        super().__init__(**data)

    @property
    def memory_variables(self) -> List[str]:
        """Define the keys that this memory will add to the chain input."""
        return [self.memory_key]

    def load_memory_variables(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Load episodic memories for the owner and format them as conversational history."""
        try:
            memories = self.client.list_memories(
                owner_id=self.owner_id,
                type="episodic",
                limit=100
            )
        except Exception as e:
            logger.error(f"Failed to load memory variables from AMP client: {e}")
            memories = []

        # Sort memories by creation timestamp (ISO 8601 strings)
        def get_created_at(cell: dict) -> str:
            created = cell.get("lifecycle", {}).get("created_at")
            if not created:
                return ""
            if isinstance(created, str):
                return created
            return created.isoformat()

        memories.sort(key=get_created_at)

        if self.return_messages:
            try:
                from langchain_core.messages import AIMessage, HumanMessage
            except ImportError:
                raise ImportError(
                    "langchain-core is required to use return_messages=True. "
                    "Install it with: pip install langchain-core"
                )
            messages = []
            for mem in memories:
                text = mem.get("content", {}).get("text", "")
                if text.startswith("Human: "):
                    messages.append(HumanMessage(content=text[len("Human: "):]))
                elif text.startswith("AI: "):
                    messages.append(AIMessage(content=text[len("AI: "):]))
                else:
                    messages.append(HumanMessage(content=text))
            return {self.memory_key: messages}
        else:
            history_str = "\n".join(mem.get("content", {}).get("text", "") for mem in memories)
            return {self.memory_key: history_str}

    def save_context(self, inputs: Dict[str, Any], outputs: Dict[str, Any]) -> None:
        """Extract input and output texts and store them as episodic memories."""
        input_text, output_text = self._get_input_output_text(inputs, outputs)

        if input_text:
            self.client.remember(
                content=f"Human: {input_text}",
                owner_id=self.owner_id,
                type="episodic"
            )
        if output_text:
            self.client.remember(
                content=f"AI: {output_text}",
                owner_id=self.owner_id,
                type="episodic"
            )

    def clear(self) -> None:
        """Forgets all memories for owner_id."""
        try:
            # Retrieve all active memories for the owner
            memories = self.client.list_memories(
                owner_id=self.owner_id,
                limit=1000
            )
            for mem in memories:
                memory_id = mem.get("id")
                if memory_id:
                    self.client.forget(memory_id)
        except Exception as e:
            logger.error(f"Failed to clear memories for owner {self.owner_id}: {e}")

    def _get_input_output_text(self, inputs: Dict[str, Any], outputs: Dict[str, Any]) -> tuple:
        """Helper to extract user query/input and assistant answer/output from context dicts."""
        # Extract input text
        if not inputs:
            input_str = ""
        elif len(inputs) == 1:
            input_str = str(next(iter(inputs.values())))
        else:
            # Fallback search for common keys
            for key in ["input", "query", "question"]:
                if key in inputs:
                    input_str = str(inputs[key])
                    break
            else:
                input_str = str(next(iter(inputs.values())))

        # Extract output text
        if not outputs:
            output_str = ""
        elif len(outputs) == 1:
            output_str = str(next(iter(outputs.values())))
        else:
            # Fallback search for common keys
            for key in ["output", "response", "answer"]:
                if key in outputs:
                    output_str = str(outputs[key])
                    break
            else:
                output_str = str(next(iter(outputs.values())))

        return input_str, output_str
