"""Event model, hash-chained event log, and the per-task pub/sub bus.

Every observable thing that happens in Airlock is an Event. Events form a
per-task hash chain, which is what makes a run receipt verifiable: given the
chain, anyone can recompute the seals and detect tampering.
"""
from __future__ import annotations

import hashlib
import json
import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

# Risk levels
RISK_INFO = 0
RISK_LOW = 1
RISK_MEDIUM = 2
RISK_HIGH = 3

RISK_LABELS = {0: "info", 1: "low", 2: "medium", 3: "high"}


def now() -> float:
    return time.time()


def canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


@dataclass
class Event:
    seq: int
    task_id: str
    type: str
    title: str
    ts: float
    risk: int = RISK_INFO
    tags: list[str] = field(default_factory=list)
    detail: dict[str, Any] = field(default_factory=dict)
    prev_hash: str = ""
    hash: str = ""

    def payload(self) -> dict[str, Any]:
        return {
            "seq": self.seq,
            "task_id": self.task_id,
            "type": self.type,
            "title": self.title,
            "ts": self.ts,
            "risk": self.risk,
            "tags": self.tags,
            "detail": self.detail,
        }

    def compute_hash(self, prev_hash: str) -> str:
        material = dict(self.payload())
        material["prev_hash"] = prev_hash
        return hashlib.sha256(canonical(material).encode()).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        d = self.payload()
        d["prev_hash"] = self.prev_hash
        d["hash"] = self.hash
        d["risk_label"] = RISK_LABELS.get(self.risk, "info")
        return d


GENESIS = "0" * 64


class EventBus:
    """Thread-safe per-task event log with fan-out to live subscribers."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._events: dict[str, list[Event]] = {}
        self._subs: dict[str, set[queue.Queue]] = {}

    def emit(
        self,
        task_id: str,
        type: str,
        title: str,
        *,
        risk: int = RISK_INFO,
        tags: list[str] | None = None,
        **detail: Any,
    ) -> Event:
        with self._lock:
            log = self._events.setdefault(task_id, [])
            ev = Event(
                seq=len(log) + 1,
                task_id=task_id,
                type=type,
                title=title,
                ts=now(),
                risk=risk,
                tags=list(tags or []),
                detail=detail,
            )
            prev = log[-1].hash if log else GENESIS
            ev.prev_hash = prev
            ev.hash = ev.compute_hash(prev)
            log.append(ev)
            for sub in self._subs.get(task_id, set()):
                sub.put_nowait(ev)
        return ev

    def history(self, task_id: str, after: int = 0) -> list[Event]:
        with self._lock:
            log = self._events.get(task_id, [])
            return list(log[after:])

    def all_events(self, task_id: str) -> list[Event]:
        with self._lock:
            return list(self._events.get(task_id, []))

    def subscribe(self, task_id: str) -> queue.Queue:
        sub: queue.Queue = queue.Queue()
        with self._lock:
            self._events.setdefault(task_id, [])
            self._subs.setdefault(task_id, set()).add(sub)
        return sub

    def unsubscribe(self, task_id: str, sub: queue.Queue) -> None:
        with self._lock:
            subs = self._subs.get(task_id)
            if subs:
                subs.discard(sub)

    def verify_chain(self, task_id: str) -> bool:
        with self._lock:
            log = list(self._events.get(task_id, []))
        prev = GENESIS
        for ev in log:
            if ev.prev_hash != prev or ev.hash != ev.compute_hash(prev):
                return False
            prev = ev.hash
        return True


bus = EventBus()
