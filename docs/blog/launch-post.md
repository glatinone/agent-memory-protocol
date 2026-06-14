# AMP: An open protocol for AI agent memory — like MCP, but for memory

We are in the golden age of AI agents. From autonomous coding assistants to multi-agent customer support workflows, agents are transitioning from simple prompt-response loops to complex, stateful systems. 

Recently, Anthropic's Model Context Protocol (MCP) introduced an elegant standard for how Large Language Models (LLMs) connect to tools and data sources. But as agent systems scale, a glaring gap remains: **memory**. How do agents store, recall, and share structured context across different frameworks, sessions, and platforms? 

Today, we are thrilled to introduce **AMP (Agent Memory Protocol)**: an open, HTTP-native protocol designed to standardize agent memory interoperability. Think of it like MCP, but for long-term memory.

---

### The Problem: Fragmented Agent Memory

In the current ecosystem, memory is highly fragmented. Every framework—whether it is LangChain, LlamaIndex, CrewAI, AutoGen, or bespoke setups like `mem0`—handles agent memory in its own proprietary way. Some store chat history in local JSON lists, others plug directly into vector databases using ad-hoc schemas, and some rely on custom graph databases.

This fragmentation creates three major challenges for developers:
1. **Framework Lock-in**: Sharing memory between a LangChain agent and a LlamaIndex agent requires building custom ETL pipelines. They speak completely different memory languages.
2. **Cognitive Siloing**: Memory is typically locked to a single session or a specific execution graph. When the session ends, the agent's context is either wiped or buried where other agents cannot access it.
3. **No Schema Consistency**: There is no industry-wide agreement on what a "memory" should contain. Without a standard schema, writing interoperable agent services is nearly impossible.

---

### Why Existing Solutions Fall Short

When developers try to solve these problems today, they usually wrap raw vector databases or use proprietary, vendor-locked managed memory services. Both approaches quickly show their limitations:

- **Vendor Lock-in**: Managed memory APIs lock your agent's state behind proprietary APIs, making cloud migrations or on-premise deployments extremely difficult.
- **Raw Vector Databases**: A vector DB is not a protocol; it lacks built-in understanding of agent identity, temporal decay, or access permissions.
- **Lack of Lifecycle Decay**: Memory should fade over time. Implementing linear or exponential decay models requires writing complex scheduler engines and background jobs from scratch.
- **Missing Access Control Lists (ACLs)**: Multi-agent security is crucial. Preventing unauthorized agents from reading sensitive billing or personal data requires writing custom database-level access layers.

---

### Introducing AMP: A Clean HTTP-Native Protocol

AMP solves these problems by decoupling agent execution from memory storage. It establishes a clean, standardized, HTTP-native interface that any agent, running on any framework or language, can use.

At the core of AMP are three main components:

1. **The Memory Cell Schema (`MemoryCell`)**: A robust, JSON-standardized data model. Each cell defines memory content, metadata, identity (owner and creator), scoring (importance and decay rate), access policies (agent ACLs), and provenance.

2. **HTTP-Native API**: AMP exposes a simple REST API (under `/amp/v1/memories`, `/amp/v1/memories/search`, `/amp/v1/memories/{id}`) that makes writing and querying memory as simple as sending a JSON payload. Access control is declared on each memory cell and enforced at the gateway layer using standard request headers like `X-AMP-Agent-ID`.

3. **Built-in Lifecycle and Decay Engine**: AMP automatically manages the lifecycle of memories. Over time, the importance score of a memory decays based on a customizable decay rate. When a memory's score drops below a threshold, the engine automatically archives or deletes it, ensuring your context window remains clean and relevant.

---

### See It In Action

To demonstrate the power of cross-agent memory sharing and built-in access control, we've created a multi-agent scenario. In this demo:
- **Agent A (CustomerServiceAgent)** learns a user preference and stores it.
- **Agent B (BillingAgent)** retrieves that preference to personalize an invoice message.
- **Agent C (MarketingAgent)** attempts to retrieve the memory but is blocked because it lacks read permissions.

Here is the complete output from running the demo script:

```text
$ python examples/multi-agent-demo/run_demo.py

[AGENT A]
CustomerServiceAgent received: 'User prefers email correspondence.'
Stored preference memory ID: mem_01J0X1F8N93M4P6Q8R0S1T3V5

[AGENT B]
BillingAgent assisted user: user_123
Retrieved response: "I will make sure to send all future billing communications and invoices to your email address, as per your preference."

[AGENT C]
MarketingAgent try_access results: 0 memories retrieved
Agent C retrieved 0 memories — access control working correctly

[SUMMARY]
AMP Demo complete. Two agents shared memory. One was blocked.
```

Because the memory cell was tagged with an access policy allowing read access only to the CustomerServiceAgent and the BillingAgent, Agent C was completely isolated from the context.

---

### Get Started

Getting started with the AMP reference server and Python SDK takes less than five minutes.

#### Step 1: Install the SDK Client
Install the Python client via pip:
```bash
pip install amp-client
```

#### Step 2: Spin Up the Reference Server
You can run the AMP reference server using Docker Compose:
```bash
git clone https://github.com/AMP-Protocol/amp.git
cd amp/server
docker compose up -d
```
Or run the server locally using Uvicorn:
```bash
pip install -e .
uvicorn amp_server.main:app --host 127.0.0.1 --port 8765
```

#### Step 3: Run the Python Demo
Once the server is running on `http://localhost:8765`, run the multi-agent demo script:
```bash
python examples/multi-agent-demo/run_demo.py
```

Here is a quick look at how you can interact with AMP programmatically in Python:

```python
from amp import AMPClient

# Initialize client
client = AMPClient(base_url="http://localhost:8765")

# Store a semantic memory
cell = client.memories.create(
    type="semantic",
    content={"text": "User prefers dark mode for UI components"},
    identity={
        "owner_id": "user-123",
        "owner_type": "user",
        "created_by": "settings-agent",
    },
    access_policy={
        "readable_by": ["settings-agent", "ui-agent"],
        "public": False
    }
)
print(f"Memory cell created with ID: {cell.id}")

# Search memory semantically from another authorized agent
results = client.memories.search(
    query="what color scheme does the user prefer?",
    owner_id="user-123",
    agent_id="ui-agent" # Must match access_policy to retrieve
)
for item in results:
    print(f"Found memory: {item.content['text']}")
```

---

### What's Next

The release of the reference server and the Python client is just the beginning for the AMP ecosystem. Our roadmap for the next few quarters includes:

1. **Polyglot SDKs**: Developing official clients for Node.js/TypeScript, Go, and Rust.
2. **Framework Plugins**: Building connectors for LangChain, LlamaIndex, CrewAI, and AutoGen so that developers can plug AMP into their existing codebases with ease.
3. **Hosted Enterprise Gateways**: Enterprise features like OAuth2/OIDC authentication, audit logging, and encrypted storage-at-rest.
4. **Community Integrations**: Building memory adapters for popular production databases (e.g., PostgreSQL, Redis, Qdrant, Pinecone) so you can back your AMP server with your existing database infrastructure.

---

### Join the Memory Revolution

AMP is fully open source under the MIT License and built on open standards. We believe that agent memory should be secure, portable, and open to all.

- 🌟 Star the repository on GitHub: [github.com/AMP-Protocol/amp](https://github.com/AMP-Protocol/amp)
- 📖 Read the full Protocol Specification: [SPEC.md](https://github.com/AMP-Protocol/amp/blob/main/SPEC.md)
- 💬 Join the discussion, file issues, and submit pull requests. Let’s build the memory layer of the agentic web together!
