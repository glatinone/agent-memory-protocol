# Show HN Submission Text

**Title:** Show HN: AMP — An open protocol for AI agent memory (like MCP but for memory)

**Body:**

Hi HN,

We've been building multi-agent systems recently, and we hit a major bottleneck: memory fragmentation. 

If you build an agent in LangChain, it writes memory in LangChain's format. If you build another agent in LlamaIndex, it uses LlamaIndex's formats. If you want them to share memory or context, you're forced to write complex, custom sync layers or lock yourself into a single framework. Furthermore, existing memory services are proprietary, managed platforms with vendor-lock APIs.

We wanted to solve this by creating a simple, open standard, similar to what MCP (Model Context Protocol) is doing for tool-calling.

We call it **AMP (Agent Memory Protocol)**.

AMP decouples memory from agent frameworks by defining:
1. A standard, self-describing **Memory Cell** schema (in JSON).
2. A clean, HTTP-native **REST API** (`POST /memories`, `POST /memories/search`, etc.).
3. A built-in **Lifecycle & Decay Engine** so that memories naturally fade from `active` to `stale` to `archived` based on usage patterns (using an exponential decay formula based on importance, confidence, and time).
4. Per-cell **Access Policies** (`readable_by`, `writable_by` lists supporting wildcards) so agents can securely share memory in multi-agent networks.
5. Compliance-by-default for privacy, including cryptographic erasure support for GDPR Article 17 (Right to Erasure).

We've launched the v0.1.0 specification along with:
- **Reference Server (Python/FastAPI):** An embedded server that uses ChromaDB for local vector storage, runs a background decay worker, and exposes FastMCP tools so you can connect it directly to Claude Desktop or Cursor out of the box.
- **Python SDK (`amp-client`):** A client library with sync, async, and LangChain memory integrations.
- **Multi-Agent Demo:** An example showing CustomerService and Billing agents sharing memory context, while a Marketing agent is blocked by cell-level access policies.

We'd love to hear your feedback on the schema design and protocol specification:
- Spec: https://github.com/AMP-Protocol/amp/blob/main/SPEC.md
- Repo: https://github.com/AMP-Protocol/amp

What do you think is the best way to model episodic vs semantic memory? How do you handle cross-agent memory in your current workflows?
