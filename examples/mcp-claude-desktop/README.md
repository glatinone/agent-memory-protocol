# Claude Desktop + AMP (MCP)

`mcp_config.json` shows the config block to add to Claude Desktop's
`claude_desktop_config.json` so Claude can call AMP's memory tools directly
over MCP.

## Setup

1. Install the server package (from the repo root):
   ```bash
   cd server
   pip install -e .
   ```
2. Copy the `"amp"` entry from `mcp_config.json` into your own
   `claude_desktop_config.json` (`%APPDATA%\Claude\claude_desktop_config.json` on
   Windows, `~/Library/Application Support/Claude/claude_desktop_config.json` on
   macOS), and set `AMP_PERSIST_DIR` to a real absolute path on your machine
   where memory data should persist.
3. Restart Claude Desktop. AMP's tools (`amp_remember`, `amp_recall`, etc.)
   appear alongside your other MCP tools.

See [docs/getting-started.md](../../docs/getting-started.md#4-claude-desktop--mcp)
for the full walkthrough.
