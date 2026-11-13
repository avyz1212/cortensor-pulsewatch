# Building Blocks Tested — PulseWatch on OpenMinion 0.1.20

Status key: ✅ exercised and verified · 🟡 implemented, not yet exercised
end-to-end · ❌ hit a problem. Verification date: 13 Nov 2026 (offline +
live-tool pass, plus the full model-backed run — see below).

## Used and verified ✅

- **Decorated tools (`@tool`)** — five run-scoped tools (`get_spot_price`,
  `get_fear_greed`, `read_watch_notes`, `save_watch_note`, `write_brief`).
  All five were called directly against the live Kraken and alternative.me
  APIs and returned correct, formatted results (BTC/ETH spot with 24h
  change, Fear & Greed today vs yesterday). Error paths behave: an
  unsupported symbol returns a readable error string instead of raising.
- **Memory (file-backed, tool-mediated)** — watch notes round-trip through
  `save_watch_note` → `read_watch_notes` works across calls, and the
  "previous note" read correctly starts empty and then returns the saved
  note, which is exactly the compare-against-last-run loop the brief needs.
- **Offline testability** — `tests/test_tools.py` passes 2/2 with no model
  and no network (fixture parsing + memory round trip). The fact that
  `@tool`-decorated functions stay directly callable from plain Python made
  this trivial to write — a genuinely nice property of the SDK.

## Model-backed run — verified 13 Nov 2026 ✅ (with findings)

- **Agent facade + model-backed run** — after `openminion setup
  --provider ollama` and pulling the model, the full workflow ran
  end-to-end against live data, twice:
  - `ask` smoke: the model emitted `get_spot_price(BTC)`, the tool
    returned Kraken's live $68,688.50, and the final answer quoted that
    exact figure (independently cross-checked against the Kraken API).
  - `brief` run 1 (session `pulsewatch-run-1b`): turn 1 batched
    `get_spot_price` ×2 + `get_fear_greed` + `read_watch_notes`; turn 2
    re-read the notes, fetched fresh BTC/F&G, then `write_brief` +
    `save_watch_note` executed (notes saved 18:19 and 18:52 UTC).
  - `brief` run 2 (session `pulsewatch-run-2`, model `qwen2.5:3b`):
    fresh fetches (BTC $68,944.60, ETH $1,946.60, F&G 20), read run 1's
    notes back, wrote a clean brief and saved its note (19:38 UTC).
    Brief preserved at `examples/model_run_brief_2026-11-13.md`; every
    number in it matches the run's own tool outputs.
- **Durable session / thread continuation** — turn 2 continues turn 1's
  thread on the same `session_id`, and the watch-note file carries memory
  across separate processes (run 2 compared against run 1's note). One
  caveat: resuming a session whose previous turn was killed mid-flight
  confused the 3B model (it jumped straight to `write_brief` from stale
  task state); a fresh session id per scheduled run behaved cleanly.
- **Typed results & diagnostics** — runs print `run_id` / `run_state`
  (e.g. ask run `676f5d41…` state=completed; brief run 1 turn 1
  `d28ae0d6…` state=completed), and the full event trail (entry path,
  policy decisions, tool calls) is inspectable in the session store.

## Rough edges found by the model run ❌→ fixed in config/code

- **qwen2.5:1.5b does not tool-call here.** In fallback *and* native
  strategy, and even in a bare Ollama `/api/chat` request with a tools
  payload, the 1.5b answered price questions from memory (three invented
  prices: $85,517.79, $37,825.00, 34,785.38 — Kraken said ~$68.7k). The
  3b emitted a perfect native tool call on the first raw test. The
  code default is now `qwen2.5:3b` (override with `PULSEWATCH_MODEL`).
- **Ollama's default context (4096) is smaller than OpenMinion's prompt**
  (~5.4k tokens of scaffolding + tool schemas), so the runner silently
  truncates. Serving with `OLLAMA_CONTEXT_LENGTH=16384` fixed it
  (verified via `/api/ps` context_length).
- **Undeclared tools prompt for confirmation.** `@tool` defaults
  (`min_scope=WRITE_SAFE`, `idempotent=False`) classify as
  unknown-reversibility writes, so a headless run stalls on an approval
  prompt. Fix in `pulsewatch.py`: the three read tools are declared
  `min_scope="READ_ONLY"` (policy: "Read-only operation allowed by
  default"), and an `approval_callback` auto-approves only the agent's
  two workspace-local write tools.
- **The brain's per-turn budget defaults to 300 s**
  (`runtime.brain_turn_timeout_seconds`). On a slow CPU that clips the
  narrative reply ("Stopped: turn time limit reached (300s/300s)")
  even though all tool work completed — and the separate gateway
  timeout (`runtime.chat_turn_timeout_seconds`, default 90 s) hard-fails
  the turn. Both were raised to 5400 s in the local config for this
  1.5-vCPU verification box; on normal hardware the defaults are fine.
- **Proxy env can break the provider client.** With this sandbox's
  `no_proxy` (bracketed IPv6 entries), httpx raised
  `InvalidURL: Invalid port: ':1]'` on every provider call. Running
  with `NO_PROXY=localhost,127.0.0.1` avoids it; environment-specific,
  but worth knowing when a local-provider run fails before any request
  is sent.
- **Speed is the real constraint on shared CPU:** prompt eval ~14 tok/s
  and generation 0.5–5 tok/s were observed, so one brief took tens of
  minutes here. The workflow design (5 tools, 2 turns) kept it feasible.

## Rough edges / feedback 🟡

- **Tool-call accessor ambiguity:** the codebase defensively checks
  `hasattr(tool, "fn")` before calling a tool outside an agent run
  (`cmd_notes`). It worked without `.fn` on 0.1.20, but the fact that the
  author felt the need to guard suggests the direct-call convention could
  be documented more clearly — it matters for testing and CLI readouts.
- **Setup is a hard prerequisite:** nothing runs before `openminion setup`
  writes provider config. Reasonable, but a friendlier failure mode
  ("run setup first, here's the command") would help first-time builders.
- **Small local models are the risk point, not the SDK:** the workflow is
  deliberately short (5 tools, 2 turns) because long tool chains are
  where small models wobble — confirmed empirically: the 1.5b never
  chained at all (see the model-run findings above), the 3b did.

## What we learned

- Designing the agent "boring on purpose" — same tools, same two turns,
  every run — makes SDK behaviour observable and repeatable, which is what
  a building-blocks test should do.
- Keeping all state behind tools (memory file, brief file) means the
  agent's least-privilege surface is five functions, and everything it
  persists can be inspected with `cat`. That pattern is worth reusing.
- Model reliability was the last unknown; it is now measured, not
  guessed: the 3b chains all five tools and grounds every number in a
  tool result, while brief *prose* quality varies (one run pasted the
  previous notes into the brief body; the next produced a clean brief).
  The recorded demo will show the same behaviour.
