# Multi-Agent Demo

Three agents share and gate access to the same AMP memory store. See
[SCENARIO.md](SCENARIO.md) for the full story: what each agent does and why
Agent C gets blocked.

## Run it

1. Start the AMP server (from the repo root):
   ```bash
   cd server
   pip install -e .
   uvicorn amp_server.main:app --host 127.0.0.1 --port 8765
   ```
2. In a second terminal, install this demo's dependencies and run it:
   ```bash
   cd examples/multi-agent-demo
   pip install -r requirements.txt
   python run_demo.py
   ```

`run_demo.py` checks the server is reachable first and exits with an error
message if it isn't. Expected output is shown in the root README's
["See It In Action"](../../README.md#see-it-in-action-multi-agent-sharing) section.
