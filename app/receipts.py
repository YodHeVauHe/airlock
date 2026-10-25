"""Run receipts: a sealed, downloadable proof of exactly what an agent run did.

A receipt is the task's event hash-chain plus a summary. Anyone can run
``verify_receipt`` on it to confirm no event was added, removed, or altered
after the fact. This is the "verifiable output" half of the pitch.
"""
from __future__ import annotations

import hashlib
import json
import time
from typing import Any

from .events import GENESIS, Event, canonical


def build_receipt(
    task_id: str,
    goal: str,
    status: str,
    events: list[Event],
    artifacts: list[dict[str, Any]],
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    chain = [
        {"seq": e.seq, "type": e.type, "title": e.title, "ts": e.ts, "risk": e.risk,
         "tags": e.tags, "detail": e.detail, "prev_hash": e.prev_hash, "hash": e.hash}
        for e in events
    ]
    final_hash = chain[-1]["hash"] if chain else GENESIS
    return {
        "receipt_version": 1,
        "task_id": task_id,
        "goal": goal,
        "status": status,
        "generated_at": time.time(),
        "event_count": len(chain),
        "head": final_hash,
        "artifacts": artifacts,
        "meta": meta or {},
        "events": chain,
    }


def verify_receipt(receipt: dict[str, Any]) -> tuple[bool, str]:
    """Recompute the whole chain. Returns (ok, reason)."""
    prev = GENESIS
    for i, ev in enumerate(receipt.get("events", []), start=1):
        if ev["seq"] != i:
            return False, f"sequence break at event {i}"
        material = {
            "seq": ev["seq"], "task_id": receipt["task_id"], "type": ev["type"],
            "title": ev["title"], "ts": ev["ts"], "risk": ev["risk"],
            "tags": ev["tags"], "detail": ev["detail"], "prev_hash": ev["prev_hash"],
        }
        expected = hashlib.sha256(canonical(material).encode()).hexdigest()
        if ev["prev_hash"] != prev:
            return False, f"broken link at event {i}"
        if ev["hash"] != expected:
            return False, f"tampered event {i}"
        prev = ev["hash"]
    if receipt.get("head") != prev:
        return False, "receipt head does not match event chain"
    if receipt.get("event_count") != len(receipt.get("events", [])):
        return False, "event count mismatch"
    return True, "ok"


def receipt_fingerprint(receipt: dict[str, Any]) -> str:
    return hashlib.sha256(canonical(receipt).encode()).hexdigest()[:16]
