# scripts/

Helpers that are not part of the shipped packages.

## `make_demo_gif.py`

Turns `docs/assets/demo-transcript.txt` into the animation on the README and the
docs home page (`docs/assets/amp-demo.gif`), plus a still frame
(`docs/assets/amp-demo.png`) for anywhere an animation will not play.

```bash
pip install pillow        # the only requirement
python scripts/make_demo_gif.py
```

It refuses to draw a line that would run past the right edge rather than
producing a picture with a truncated command in it, and it refuses a transcript
line that looks like a marker (`*Result`) but is missing the space the format
asks for (`* Result`) - that mistake renders as ordinary output, so it is
invisible in the result and easy to make twice.

### Re-recording the transcript

The transcript is real output, not written by hand. To refresh it after a change
to the server or the demo:

```bash
# 1. start the server (the demo talks to https://localhost:8765)
cd server && pip install -e . && uvicorn amp_server.main:app --port 8765

# 2. run the demo it shows
cd examples/multi-agent-demo && python run_demo.py

# 3. ask the same question as two different agents, and copy the replies
curl -s http://localhost:8765/amp/v1/memories/search \
  -H 'X-AMP-Agent-ID: agent_billing_v1' -H 'Content-Type: application/json' \
  -d '{"query": "contact preference", "owner_id": "user_123", "limit": 3}'
curl -s http://localhost:8765/amp/v1/memories/search \
  -H 'X-AMP-Agent-ID: agent_marketing' -H 'Content-Type: application/json' \
  -d '{"query": "contact preference", "owner_id": "user_123", "limit": 3}'
```

Paste the results into `docs/assets/demo-transcript.txt` and run the generator.
Keep the file honest: if the output changes, the picture changes with it. Never
edit the transcript to say something the server did not.
