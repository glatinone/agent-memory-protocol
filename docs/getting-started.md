# Getting Started with AMP

Get a memory server running and store your first memory in under 5 minutes.

**Prerequisites:** Docker, or Python 3.11+

---

## 1. Installation

**Docker (recommended)**

```bash
git clone https://github.com/AMP-Protocol/amp.git
cd amp/server
docker compose up -d
```

The server starts on `http://localhost:8765`. Confirm it's up:

```bash
curl http://localhost:8765/amp/v1/health
# {"status":"ok","amp_version":"0.1.0"}
```

Data is persisted to `amp/server/data/` on your host via the Docker volume.

**Without Docker**

```bash
cd amp/server
pip install -e .
uvicorn amp_server.main:app --host 0.0.0.0 --port 8765
```

---

## 2. Your first memory

Three commands — create, search, delete.

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

Copy the `id` from the response — you'll need it in a moment.

```json
{
  "id": "01J5A3B7K9M2N4P6Q8R0S1T3V5",
  "type": "semantic",
  "lifecycle": { "status": "active" },
  ...
}
```

**Search for it**

```bash
curl -X POST http://localhost:8765/amp/v1/memories/search \
  -H "Content-Type: application/json" \
  -d '{
    "query": "what language does the user prefer?",
    "owner_id": "user-123"
  }'
```

```json
{
  "results": [
    { "id": "01J5A3B7K9M2N4P6Q8R0S1T3V5", "content": { "text": "User prefers Python for backend development" } }
  ],
  "total": 1,
  "query": "what language does the user prefer?"
}
```

**Delete it**

```bash
curl -X DELETE http://localhost:8765/amp/v1/memories/01J5A3B7K9M2N4P6Q8R0S1T3V5
# 204 No Content
```

Deletion is a soft-delete: `lifecycle.status` is set to `"deleted"` and the cell is excluded from future searches.

---

## 3. Python quickstart

The official Python SDK client package `amp-client` makes it easy to integrate AMP into your python-based agents. Install it using pip:

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
        "AMP_PERSIST_DIR": "C:\\path\\to\\your\\persistent\\dir"
      }
    }
  }
}
```

> [!IMPORTANT]
> The command must be run in an environment where the `amp-server` package (containing the `amp_server` module) is installed. Ensure your python environment path or active virtual environment is correctly accessible to the command.

