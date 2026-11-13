#!/usr/bin/env python3
"""PulseWatch - a crypto market-watch brief agent built on the OpenMinion 0.1 SDK.

One useful, repeatable workflow:
  1. Fetch live spot prices (Kraken public API, no key) and the Fear & Greed
     index (alternative.me public API, no key) through run-scoped tools.
  2. Recall the previous watch note from the agent's durable local memory.
  3. Write a short markdown market brief into ``briefs/``.
  4. Save a fresh watch note so the *next* run can report what changed.

Building blocks exercised: decorated tools, durable sessions with explicit
thread continuation, memory across runs, typed run results + diagnostics.

Usage:
    python pulsewatch.py brief            # full workflow (two turns, one session)
    python pulsewatch.py ask "question"   # one free-form turn in the same session
    python pulsewatch.py notes            # print stored watch notes (no model)

Environment:
    PULSEWATCH_MODEL   model id for the Agent (default: qwen2.5:3b via the
                       Ollama connection created by `openminion setup`)
    PULSEWATCH_SESSION session id (default: pulsewatch-demo)
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from openminion import Agent, tool

ROOT = Path(__file__).resolve().parent
MEMORY_FILE = ROOT / "memory" / "watch_notes.jsonl"
BRIEF_DIR = ROOT / "briefs"

# Default model: qwen2.5:3b. The 1.5b was tried first (2026-11-13) and
# reliably answered from memory instead of emitting tool calls, which breaks
# this agent's core rule (never invent numbers). The 3b emits proper native
# tool calls through Ollama; see BUILDING_BLOCKS.md.
MODEL = os.environ.get("PULSEWATCH_MODEL", "qwen2.5:3b")
SESSION_ID = os.environ.get("PULSEWATCH_SESSION", "pulsewatch-demo")

KRAKEN_PAIRS = {"BTC": "XBTUSD", "ETH": "ETHUSD", "SOL": "SOLUSD"}


def _get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "pulsewatch/0.1"})
    with urllib.request.urlopen(req, timeout=20) as resp:  # proxy-aware via env
        return json.loads(resp.read().decode("utf-8"))


# --------------------------------------------------------------------------
# Tools (run-scoped: the agent only sees these during a PulseWatch run)
# --------------------------------------------------------------------------
@tool(min_scope="READ_ONLY")
def get_spot_price(symbol: str) -> str:
    """Get the current USD spot price and 24h change for BTC, ETH, or SOL."""
    pair = KRAKEN_PAIRS.get(symbol.strip().upper())
    if pair is None:
        return f"error: unsupported symbol {symbol!r}; use BTC, ETH, or SOL"
    data = _get_json(f"https://api.kraken.com/0/public/Ticker?pair={pair}")
    if data.get("error"):
        return f"error: kraken returned {data['error']}"
    ticker = next(iter(data["result"].values()))
    last = float(ticker["c"][0])
    open_ = float(ticker["o"])
    change = (last - open_) / open_ * 100.0
    return (
        f"{symbol.upper()} spot ${last:,.2f} "
        f"({change:+.2f}% vs today's open ${open_:,.2f}, "
        f"24h high ${float(ticker['h'][1]):,.2f}, low ${float(ticker['l'][1]):,.2f})"
    )


@tool(min_scope="READ_ONLY")
def get_fear_greed() -> str:
    """Get today's and yesterday's Crypto Fear & Greed index values."""
    data = _get_json("https://api.alternative.me/fng/?limit=2")
    rows = data.get("data", [])
    if len(rows) < 2:
        return "error: fear & greed index unavailable"
    today, yday = rows[0], rows[1]
    return (
        f"Fear & Greed today: {today['value']} ({today['value_classification']}); "
        f"yesterday: {yday['value']} ({yday['value_classification']})"
    )


@tool(min_scope="READ_ONLY")
def read_watch_notes(limit: int = 3) -> str:
    """Read the most recent saved watch notes (the agent's memory of past runs)."""
    if not MEMORY_FILE.exists():
        return "no watch notes saved yet"
    lines = [ln for ln in MEMORY_FILE.read_text().splitlines() if ln.strip()]
    notes = [json.loads(ln) for ln in lines[-max(1, limit):]]
    return "\n".join(f"[{n['saved_at']}] {n['note']}" for n in notes) or "no notes"


@tool
def save_watch_note(note: str) -> str:
    """Save a one-line watch note so future runs can compare against it."""
    MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "saved_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "note": note.strip(),
    }
    with MEMORY_FILE.open("a") as fh:
        fh.write(json.dumps(record) + "\n")
    return f"saved watch note for {record['saved_at']}"


@tool
def write_brief(markdown: str) -> str:
    """Write the market brief markdown to briefs/brief-<date>.md and return the path."""
    BRIEF_DIR.mkdir(parents=True, exist_ok=True)
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path = BRIEF_DIR / f"brief-{day}.md"
    path.write_text(markdown.strip() + "\n")
    return f"brief written to {path}"


INSTRUCTIONS = """You are PulseWatch, a market-watch assistant.
Rules:
- Never invent numbers. Get prices with get_spot_price and sentiment with
  get_fear_greed before writing anything.
- Keep every answer short and factual, with the actual numbers from tools.
- When asked to prepare a brief: fetch BTC and ETH prices and the Fear & Greed
  index, read the previous watch notes, write the brief with write_brief
  (markdown: title, date, price lines, sentiment line, one 'What changed'
  line vs the previous note, one 'Watch next' line), then save_watch_note with
  a one-line summary containing both prices and the sentiment value.
"""


def make_agent() -> Agent:
    return Agent(
        instructions=INSTRUCTIONS,
        model=MODEL,
        tools=[
            get_spot_price,
            get_fear_greed,
            read_watch_notes,
            save_watch_note,
            write_brief,
        ],
        session_id=SESSION_ID,
        name="pulsewatch",
    )


# OpenMinion's action policy asks for confirmation before tools whose
# reversibility it cannot prove. PulseWatch is meant to run unattended
# (cron, demo), so approve exactly its two workspace-local write tools here;
# anything else still prompts. The read tools above are declared READ_ONLY
# and never prompt.
_LOCAL_WRITE_TOOLS = {"save_watch_note", "write_brief"}


def _approve_local_writes(tool_name: str, args: dict, approval_id: str) -> bool:
    return tool_name.rpartition(".")[2] in _LOCAL_WRITE_TOOLS


def cmd_brief() -> int:
    with make_agent() as agent:
        turn1 = agent.run(
            "Fetch the current BTC and ETH spot prices and the Fear & Greed "
            "index, then read the previous watch notes. Reply with the raw "
            "numbers and what the previous note said.",
            approval_callback=_approve_local_writes,
        )
        print("\n--- turn 1 (gather) ---\n" + turn1.text)
        print(f"[run_id={turn1.run_id} state={turn1.run_state}]")
        turn2 = agent.run(
            "Now prepare today's market brief from those numbers: write the "
            "brief file, then save a one-line watch note for the next run. "
            "Confirm what you wrote.",
            approval_callback=_approve_local_writes,
        )
        print("\n--- turn 2 (brief + remember) ---\n" + turn2.text)
        print(f"[run_id={turn2.run_id} state={turn2.run_state}]")
    return 0


def cmd_ask(prompt: str) -> int:
    with make_agent() as agent:
        result = agent.run(prompt, approval_callback=_approve_local_writes)
        print(result.text)
        print(f"[run_id={result.run_id} state={result.run_state}]")
    return 0


def cmd_notes() -> int:
    print(read_watch_notes.fn(limit=10) if hasattr(read_watch_notes, "fn") else read_watch_notes(limit=10))
    return 0


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args or args[0] == "brief":
        raise SystemExit(cmd_brief())
    if args[0] == "ask" and len(args) > 1:
        raise SystemExit(cmd_ask(" ".join(args[1:])))
    if args[0] == "notes":
        raise SystemExit(cmd_notes())
    print(__doc__)
    raise SystemExit(2)
