"""Sandbox contract shared by every driver.

A driver receives an ExecRequest and must:
  1. create a fresh, isolated environment,
  2. run the request's code inside it with the requested caps,
  3. stream observations through on_event,
  4. ALWAYS destroy the environment (success, failure, timeout — no exceptions).

Secrets never cross this boundary: drivers construct the sandbox environment
from scratch and never forward the control plane's env or API keys.
"""
from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class ExecRequest:
    task_id: str
    code: str
    files: dict[str, bytes] = field(default_factory=dict)   # input files -> /workspace
    timeout_s: int = 60
    mem_mb: int = 512
    cpus: float = 1.0
    pids: int = 128
    max_output_bytes: int = 256 * 1024
    max_artifact_bytes: int = 20 * 1024 * 1024
    label: str = "run"          # short label for events, e.g. "attempt 1"

    def file_manifest(self) -> list[str]:
        return sorted(self.files.keys())


@dataclass
class ExecResult:
    exit_code: int
    stdout: str
    stderr: str
    artifacts: dict[str, bytes] = field(default_factory=dict)  # new/changed files
    duration_s: float = 0.0
    killed_reason: str | None = None     # "timeout" | "resource" | None
    meta: dict[str, Any] = field(default_factory=dict)         # driver details for the UI

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and self.killed_reason is None


EventFn = Callable[[str, dict], None]   # (event_type, payload) — orchestrator turns these into Events


class SandboxDriver(abc.ABC):
    name: str = "abstract"

    @abc.abstractmethod
    def run(self, req: ExecRequest, on_event: EventFn) -> ExecResult: ...

    def describe(self) -> dict[str, Any]:
        return {"driver": self.name}
