"""Offline tests for PulseWatch's tool logic (no model, no network).

Run:  python tests/test_tools.py
Covers the Kraken response parsing used by get_spot_price and the
note-store round trip used by save_watch_note / read_watch_notes.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pulsewatch


def test_kraken_parse(monkeypatch_data: dict) -> None:
    pulsewatch._get_json = lambda url: monkeypatch_data  # noqa: SLF001
    out = pulsewatch.get_spot_price("BTC")
    assert "BTC spot $71,891.00" in out, out
    assert "24h high" in out, out
    print("ok: kraken ticker parsing ->", out)


def test_notes_roundtrip(tmp_memory: Path) -> None:
    pulsewatch.MEMORY_FILE = tmp_memory
    msg = pulsewatch.save_watch_note("BTC 71891, F&G 28 Fear")
    assert "saved watch note" in msg, msg
    out = pulsewatch.read_watch_notes(3)
    assert "BTC 71891, F&G 28 Fear" in out, out
    print("ok: watch-note round trip ->", out)


if __name__ == "__main__":
    fixture = {
        "error": [],
        "result": {
            "XXBTZUSD": {
                "c": ["71891.00000", "0.00002674"],
                "h": ["74115.60000", "74718.10000"],
                "l": ["71133.40000", "71133.40000"],
                "o": "73920.10000",
            }
        },
    }
    test_kraken_parse(fixture)
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        test_notes_roundtrip(Path(td) / "notes.jsonl")
    print("ALL TESTS PASSED")
