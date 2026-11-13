# PulseWatch — a market-watch brief agent on OpenMinion 0.1

PulseWatch is a small, working agent built with the **OpenMinion 0.1 Python
SDK** for Cortensor Hackathon #5. Once a day (or on demand) it:

1. fetches live BTC/ETH spot prices (Kraken public API — no key needed) and
   the Crypto Fear & Greed index (alternative.me — no key needed) through
   run-scoped tools,
2. recalls the previous run's watch note from its durable local memory,
3. writes a short markdown market brief to `briefs/brief-<date>.md`, and
4. saves a fresh watch note, so the next run can report *what changed*.

It is deliberately boring infrastructure: the same workflow, the same tools,
every run — which makes it a good probe of OpenMinion's core building blocks
(tools, sessions, thread continuation, memory, diagnostics). Findings are in
[BUILDING_BLOCKS.md](BUILDING_BLOCKS.md).

## Quickstart

Prerequisites: Python 3.11+, and a model. The reference setup uses a local
model through [Ollama](https://ollama.com) so the whole demo runs with **no
API keys and no hosted account**:

```bash
# 1. Local model runtime (any OpenMinion provider works; see `openminion
#    setup --list-providers` — OpenAI, Anthropic, OpenRouter, Cortensor
#    Portal, ... just need their usual API key instead)
ollama pull qwen2.5:3b
ollama serve &

# 2. Python env + SDK
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt        # openminion==0.1.20

# 3. One-time OpenMinion provider setup (writes local config only)
openminion setup --no-chat --provider ollama --model qwen2.5:3b

# 4. Run the workflow
python pulsewatch.py brief             # two turns, one durable session
python pulsewatch.py ask "What changed since the last brief?"
python pulsewatch.py notes             # raw memory readout (no model)
```

Run `brief` twice and the second brief's *What changed* line is computed
against the note the first run saved — that is the memory loop working.

## How it maps to the SDK

| OpenMinion building block | Where in PulseWatch |
| --- | --- |
| Decorated tools (`@tool`) | `get_spot_price`, `get_fear_greed`, `read_watch_notes`, `save_watch_note`, `write_brief` in `pulsewatch.py` |
| Agent facade | `Agent(instructions=..., model=..., tools=[...], session_id=...)` |
| Durable session + thread continuation | turn 2 of `cmd_brief` continues the thread turn 1 started; the same `session_id` is reused across processes |
| Memory | `memory/watch_notes.jsonl`, written/read only through tools |
| Typed results & diagnostics | every run prints `run_id` / `run_state` from `AgentRunResult`; inspect with `openminion status runs` |
| Permissions / least privilege | the agent gets exactly five run-scoped tools — no shell, no generic file access; writes are confined to `briefs/` and `memory/` by the tool implementations |

## Layout

```
pulsewatch.py            the agent, its tools, and the CLI driver
tests/test_tools.py      offline tests (fixture parsing + memory round trip)
examples/sample_brief.md a real brief produced by the reference setup
briefs/                  generated briefs (gitignored)
memory/                  watch notes (gitignored)
BUILDING_BLOCKS.md       blocks tested, what worked, what broke, feedback
```

## Model notes

The reference run uses `qwen2.5:3b` on CPU via Ollama: small, free, and
reliable at short tool chains. (`qwen2.5:1.5b` was tried first and, in
repeated verified runs on 13 Nov 2026, answered price questions from memory
instead of emitting tool calls — fatal for an agent whose core rule is
"never invent numbers" — so the default moved up to the 3b; see
BUILDING_BLOCKS.md.) Any larger model/provider can be swapped in with
`PULSEWATCH_MODEL` + the matching `openminion setup` connection — no code
changes.

## License

Apache-2.0 (same as OpenMinion). Market data: Kraken + alternative.me public
endpoints; not financial advice.
