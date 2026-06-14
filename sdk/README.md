# AMP Python Client SDK

`amp-client` is the official Python SDK client for the **Agent Memory Protocol (AMP)**. It provides standard synchronous and asynchronous clients to interact with an AMP memory server, as well as native integrations with LangChain.

## Installation

Install the package using pip:

```bash
pip install amp-client
```

To include LangChain support:

```bash
pip install "amp-client[langchain]"
```

---

## Quickstart

Store and retrieve memories with the synchronous client in under 5 lines:

```python
from amp_client import AMPClient

client = AMPClient("http://localhost:8765", agent_id="agent_assistant")
client.remember(content="User prefers email correspondence.", owner_id="user_123")
memories = client.recall(query="communication preferences", owner_id="user_123")
print(memories[0]["content"]["text"])
```

---

## Full API Reference

### `AMPClient` (Sync)

#### `__init__(server_url: str, agent_id: str)`
Initializes the client. Auto-normalizes the `server_url` to append `/amp/v1`.
- `server_url`: Base URL of the AMP server.
- `agent_id`: Identifier of the client agent (maps to `X-AMP-Agent-ID` header).

#### `remember(content: str | dict, owner_id: str, type: str = "semantic", importance: float = 0.5, readable_by: list[str] | None = None) -> dict`
Store a piece of information.
- `content`: Memory content (either a string, or a dict with `text` and `metadata`).
- `owner_id`: ID of the owner entity (e.g. user ID).
- `type`: Memory type (`"semantic"`, `"episodic"`, or `"procedural"`).
- `importance`: Float score in range `[0.0, 1.0]`.
- `readable_by`: Optional list of agent ID patterns permitted to read this cell.
- **Returns**: Dictionary representation of the created `MemoryCell`.

#### `recall(query: str, owner_id: str, limit: int = 5, include_stale: bool = False) -> list[dict]`
Perform semantic search for memories.
- `query`: Natural language query.
- `owner_id`: Owner ID of target memories.
- `limit`: Maximum results to return.
- `include_stale`: If `True`, includes stale cells in search.
- **Returns**: List of matching `MemoryCell` dictionaries.

#### `forget(memory_id: str) -> bool`
Archive and delete a memory.
- `memory_id`: The ID of the memory cell.
- **Returns**: `True` if successfully deleted.

#### `list_memories(owner_id: str, type: str | None = None, limit: int = 20) -> list[dict]`
Filter active memories by structured criteria (no semantic search).
- `owner_id`: Owner ID.
- `type`: Optional memory type filter.
- `limit`: Maximum results to return.
- **Returns**: List of active `MemoryCell` dictionaries.

#### `health() -> bool`
Check server health status.
- **Returns**: `True` if healthy.

---

## Async Client (`AsyncAMPClient`)

The asynchronous client has the exact same API surface as `AMPClient`, but all network calls must be awaited. It also implements async context manager support:

```python
import asyncio
from amp_client import AsyncAMPClient

async def main():
    async with AsyncAMPClient("http://localhost:8765", "agent_assistant") as client:
        await client.remember("User likes dark mode.", "user_123")
        results = await client.recall("UI preferences", "user_123")
        print(results)

asyncio.run(main())
```

---

## LangChain Integration

Use `AMPMemory` as a drop-in replacement for standard conversation memories to persist agent memory in AMP.

```python
from langchain.chains import ConversationChain
from amp_client import AMPClient
from amp_client.integrations.langchain import AMPMemory

client = AMPClient("http://localhost:8765", agent_id="chatbot_agent")
memory = AMPMemory(client=client, owner_id="user_john", memory_key="history")

conversation = ConversationChain(
    llm=chat_model,
    memory=memory,
    verbose=True
)

response = conversation.predict(input="Hi, my name is John and I write Python.")
```

---

## Error Handling

All client errors resulting from non-2xx responses or connection issues raise `AMPError`.

```python
from amp_client import AMPClient, AMPError

client = AMPClient("http://localhost:8765", agent_id="agent_test")
try:
    client.remember(content="", owner_id="user_123")  # Invalid schema
except AMPError as e:
    print(f"Error occurred: {e} (Status: {e.status_code})")
```
