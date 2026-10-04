# Getting Started with AMP

Get a memory server running and store your first memory in under 5 minutes.

**Prerequisites:** Docker, or Python 3.11+

---

## 1. Installation

**Docker (recommended)**

```bash
git clone https://github.com/glatinone/agent-memory-protocol.git
cd agent-memory-protocol/server
docker compose up -d
```

The server starts on `http://localhost:8765`. Confirm it's up:

```bash
curl http://localhost:8765/amp/v1/health
# {"status":"ok","amp_version":"0.1.0"}
```

Data is persisted to `agent-memory-protocol/server/data/` on your host via the Docker volume.

**Without Docker**

```bash
cd agent-memory-protocol/server
pip install -e .
uvicorn amp_server.main:app --host 0.0.0.0 --port 8765
```

---

## 2. Your first memory

Three commands - create, search, delete.

**Create a memory**

```bash
curl -X POST http://localhost:8765/amp/v1/memories \
  -H "Content-Type: application/json" \
  -d '{
    "type": "semantic",
    "content": {
      "text": "User prefers Python for backend development"
    },
    "identity": {
      "owner_id": "user-123",
      "owner_type": "user",
      "created_by": "my-agent"
    }
  }'
```

Copy the `id` from the response - you'll need it in a moment.

```json
{
  "id": "mem_01J5A3B7K9M2N4P6Q8R0S1T3V5",
  "type": "semantic",
  "lifecycle": { "status": "active" },
  ...
}
```

**Search for it**

```bash
curl -X POST http://localhost:8765/amp/v1/memories/search \
  -H "X-AMP-Agent-ID: my-agent" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "what language does the user prefer?",
    "owner_id": "user-123"
  }'
```

```json
{
  "results": [
    { "id": "mem_01J5A3B7K9M2N4P6Q8R0S1T3V5", "content": { "text": "User prefers Python for backend development" } }
  ],
  "returned": 1,
  "query": "what language does the user prefer?"
}
```

**Delete it**

```bash
# a cell has to be archived before it can be deleted; the protocol has no
# "delete it whatever state it is in" step
curl -X PATCH http://localhost:8765/amp/v1/memories/mem_01J5A3B7K9M2N4P6Q8R0S1T3V5 \
  -H "X-AMP-Agent-ID: my-agent" \
  -H "Content-Type: application/json" \
  -d '{"lifecycle": {"status": "archived"}}'

curl -X DELETE http://localhost:8765/amp/v1/memories/mem_01J5A3B7K9M2N4P6Q8R0S1T3V5 \
  -H "X-AMP-Agent-ID: my-agent"
# 204 No Content
```

Deletion is a soft-delete: `lifecycle.status` is set to `"deleted"` and the cell is excluded from
future searches. Deleting a cell that is not `archived` answers `409 INVALID_TRANSITION` - the
two-step order is deliberate, so a delete cannot race the decay engine.

---

## 3. Python quickstart

The official Python SDK client package `amp-client` makes it easy to integrate AMP into your python-based agents:

```bash
pip install amp-client
```

Use the following quickstart pattern to manage memories with the client:

```python
from amp_client import AMPClient

client = AMPClient("http://localhost:8765", agent_id="my-agent")

# Store a memory
cell = client.remember(
    content="User prefers Python for backend development",
    owner_id="user-123",
    type="semantic"
)
print(cell["id"])

# Search
results = client.recall(
    query="what language does the user prefer?",
    owner_id="user-123"
)
for r in results:
    print(r["content"]["text"])
    
# Delete
client.forget(cell["id"])
```

---

## 4. Claude Desktop + MCP

AMP includes a Model Context Protocol (MCP) server that exposes memory operations directly to LLM clients. You can configure Claude Desktop to connect to the MCP server by adding it to your `claude_desktop_config.json` configuration file.

### Configuration

Add the following JSON snippet to your `claude_desktop_config.json` (typically located at `%APPDATA%\Claude\claude_desktop_config.json` on Windows or `~/Library/Application Support/Claude/claude_desktop_config.json` on macOS):

```json
{
  "mcpServers": {
    "amp": {
      "command": "python",
      "args": ["-m", "amp_server.mcp_server"],
      "env": {
        "AMP_PERSIST_DIR": "C:\\path\\to\\your\\persistent\\dir",
        "AMP_MCP_AGENT_ID": "claude-desktop"
      }
    }
  }
}
```

`AMP_MCP_AGENT_ID` is the agent this MCP server acts as. Set it to something that
names the client, and set a different value for each one you run: every access rule
is decided from this identity, so a shared value means every MCP client pointed at
the same store is the same agent - cells one of them created are readable by the
others, and `readable_by` patterns naming real agent ids never match. Unset, it
falls back to `mcp_client`, which is a shared namespace rather than an identity.

> [!IMPORTANT]
> The command must be run in an environment where the `amp-server` package (containing the `amp_server` module) is installed. Ensure your python environment path or active virtual environment is correctly accessible to the command.

---

## 5. Choosing an embedding provider

Memory cells are stored as vectors, so something has to turn text into them. By
default the server uses the model Chroma ships (a local all-MiniLM-L6-v2), which
needs no configuration and no network.

To use a different one, set `AMP_EMBEDDING_PROVIDER`. The alternative that ships
with the server is `openai-compatible`: it speaks the OpenAI `/embeddings` API,
so it also works with Ollama, LM Studio, vLLM, and any other service that mirrors
that shape.

```bash
export AMP_EMBEDDING_PROVIDER=openai-compatible
export AMP_EMBEDDING_BASE_URL=http://localhost:11434/v1   # your service
export AMP_EMBEDDING_MODEL=nomic-embed-text
export AMP_EMBEDDING_API_KEY=...        # optional; omit for a local server
export AMP_EMBEDDING_DIMENSIONS=768     # optional; reported at GET /spec
```

With this provider selected, memory text is sent to that endpoint. That is what
choosing it means, and it is why the default stays local.

Two things to know before switching a server that already holds data:

- **Vectors from different models are not comparable.** Cells written under the
  old provider were embedded in a different space, so search stops being
  meaningful. Use a fresh `AMP_PERSIST_DIR`, or re-create the cells; re-embedding
  in place is not automated.
- **An unknown provider name stops the server from starting** instead of falling
  back to the default, so a typo cannot quietly produce vectors nobody can search
  consistently.

`GET /spec` reports the provider in use and the width of the vectors it produces.

---

## 6. Choosing a storage backend

By default cells live in an embedded Chroma database under `AMP_PERSIST_DIR`, which
suits a single process and a quick start.

For anything else, `AMP_STORAGE_BACKEND=postgres` keeps cells in PostgreSQL with
the `pgvector` extension, so AMP can sit next to data you already back up and
monitor, and more than one server process can share it.

```bash
pip install "amp-server[postgres]"          # the optional driver
export AMP_STORAGE_BACKEND=postgres
export AMP_POSTGRES_DSN=postgresql://user:password@localhost:5432/amp
```

The adapter creates the `vector` extension, its table and its indexes on start.

With the Compose file in `server/`, `docker compose --profile postgres up -d`
brings up a Postgres-backed deployment using the `pgvector/pgvector:pg16` image.

Both backends are held to the same behaviour, and CI proves it rather than
asserting it: a job runs the whole storage contract suite against a real
Postgres, including the test that the two backends rank the same data in the same
order. `GET /spec` reports which one is in use under `storage_backends`.

The embedding-provider rules in step 5 apply to either backend: switching
provider invalidates the vectors already stored.

---

## 7. Turning on API keys (optional)

By default the server trusts the `X-AMP-Agent-ID` header, which is what the spec's
binding describes: the header names the agent, and every access rule is decided
from it. Anyone who can reach the port can therefore claim any agent id.

To require proof, point the server at a key store:

```bash
python -m amp_server.auth hash 'the-agent-key'   # prints the value to paste
```

```json title="api-keys.json"
{
  "agent_assistant": "sha256:2c26b46b68ffc68ff99b453c1d30413413422d706483bfa0f98a5e886266e7ae"
}
```

```bash
export AMP_API_KEYS_FILE=/etc/amp/api-keys.json
```

Clients then send the key alongside the identity header:

```python
client = AMPClient("http://localhost:8765", "agent_assistant", api_key="the-agent-key")
```

The file stores digests rather than keys, and a store that cannot be read stops
the server rather than falling back to trusting the header. Full detail, including
the two rules this changes, is in the [API reference](api-reference.md#authentication).
