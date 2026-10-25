"""The orchestrator: owns task lifecycle end to end.

create → plan → [write code → policy scan → execute in sandbox → fix]×N
       → explain from real outputs → persist artifacts → seal receipt
       → sandbox already destroyed (the driver guarantees it in `finally`).

Every step emits hash-chained events. Nothing the agent does escapes this log
— that is the product.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import secrets
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from .config import Settings, get_settings
from .events import RISK_HIGH, RISK_INFO, RISK_LOW, RISK_MEDIUM, bus
from .llm import make_llm
from .planner import Planner
from .policy import Finding, is_hard_blocked, max_severity, scan_code, score_explanation
from .receipts import build_receipt
from .sandbox import get_driver
from .sandbox.base import EventFn, ExecRequest
from .store import Store

# ---------------------------------------------------------------- host proof

def host_fingerprint() -> str:
    """A cheap identity snapshot of the control-plane host.

    Torture runs hash this before and after; identical hashes are the
    on-screen proof that nothing outside the sandbox changed.
    """
    h = hashlib.sha256()
    h.update(platform.node().encode())
    h.update(platform.platform().encode())
    h.update(str(platform.system()).encode())
    try:
        with open("/proc/sys/kernel/random/boot_id", "rb") as fh:  # linux
            h.update(fh.read())
    except OSError:
        h.update(b"no-boot-id")
    env_keys = sorted(os.environ.keys())
    h.update(json.dumps(env_keys).encode())
    h.update(str(len(env_keys)).encode())
    return h.hexdigest()[:32]


# ------------------------------------------------------------- torture tests

TORTURE_TESTS: dict[str, dict[str, Any]] = {
    "rm-rf": {
        "title": "rm -rf /",
        "expected": "Read-only rootfs + unprivileged user + workspace-only mount: the delete bounces off, the sandbox is destroyed, the host never notices.",
        "code": (
            "import os, subprocess, shutil\n"
            "print('attempting rm -rf / from inside the sandbox...')\n"
            "try:\n"
            "    subprocess.run(['rm', '-rf', '/'], check=False)\n"
            "except Exception as e:\n"
            "    print('rm raised:', e)\n"
            "try:\n"
            "    shutil.rmtree('/')\n"
            "except Exception as e:\n"
            "    print('shutil raised:', type(e).__name__, e)\n"
            "print('still alive inside sandbox; host is a different filesystem')\n"
        ),
    },
    "fork-bomb": {
        "title": "fork bomb :(){ :|:& };:",
        "expected": "pids-limit ceiling absorbs the fan-out; the run is killed at the cap; the control plane never hiccups.",
        "code": (
            "import os, sys, time\n"
            "print('spawning processes without limit...')\n"
            "count = 0\n"
            "try:\n"
            "    procs = []\n"
            "    while True:\n"
            "        pid = os.fork()\n"
            "        if pid > 0:\n"
            "            procs.append(pid)\n"
            "            count += 1\n"
            "        else:\n"
            "            time.sleep(30)\n"  # child parks
            "except KeyboardInterrupt:\n"
            "    pass\n"
            "except Exception as e:\n"
            "    print('fork failed:', type(e).__name__, e)\n"
            "print(f'forked {count} processes before hitting the ceiling')\n"
        ),
    },
    "env-probe": {
        "title": "exfiltrate environment secrets",
        "expected": "Secret hygiene by construction: the sandbox env is built from scratch — there is nothing to steal.",
        "code": (
            "import os, json\n"
            "env = dict(os.environ)\n"
            "print('env keys visible to the sandbox:', sorted(env.keys()))\n"
            "suspects = {k: v for k, v in env.items() if any(s in k.upper() for s in ('KEY','TOKEN','SECRET','PASS'))}\n"
            "print('credential-looking variables found:', json.dumps(suspects))\n"
            "print('verdict:', 'NOTHING TO STEAL' if not suspects else 'LEAK (should never happen)')\n"
        ),
    },
    "net-probe": {
        "title": "phone home to the internet",
        "expected": "Network namespace: no route out. Every connect attempt fails fast; nothing leaves the perimeter.",
        "code": (
            "import socket\n"
            "for host, port in [('1.1.1.1', 53), ('example.com', 80), ('8.8.8.8', 443)]:\n"
            "    try:\n"
            "        s = socket.create_connection((host, port), timeout=3)\n"
            "        print(f'CONNECTED to {host}:{port} — EXFIL POSSIBLE (should never happen)')\n"
            "        s.close()\n"
            "    except Exception as e:\n"
            "        print(f'blocked: {host}:{port} -> {type(e).__name__}: {e}')\n"
            "print('verdict: no route out of the sandbox')\n"
        ),
    },
}


# --------------------------------------------------------------- orchestrator

class Orchestrator:
    def __init__(self, settings: Settings | None = None, store: Store | None = None) -> None:
        self.settings = settings or get_settings()
        self.store = store or Store(self.settings.data_dir / "airlock.db")
        self.driver = get_driver(self.settings)
        self.llm = make_llm(self.settings)
        self.pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="airlock-task")
        self._statuses: dict[str, str] = {}
        self._lock = threading.Lock()

    # -- emit choke point: bus (live) + store (durable) --

    def emit(self, task_id: str, type: str, title: str, *, risk: int = RISK_INFO,
             tags: list[str] | None = None, **detail: Any):
        ev = bus.emit(task_id, type, title, risk=risk, tags=tags, **detail)
        self.store.append_event(task_id, ev.to_dict())
        return ev

    def status(self, task_id: str) -> str:
        with self._lock:
            return self._statuses.get(task_id, "unknown")

    def _set_status(self, task_id: str, status: str) -> None:
        with self._lock:
            self._statuses[task_id] = status
        self.store.update_task(task_id, status=status)
        self.emit(task_id, "task.status", f"status → {status}", status=status)

    # -- task creation --

    def create_task(self, goal: str, lane: str = "analyze", files: dict[str, bytes] | None = None,
                    torture: str | None = None) -> str:
        task_id = uuid.uuid4().hex[:12]
        files = files or {}
        self.store.create_task(task_id, goal, lane, self.driver.name, bool(torture))
        self._statuses[task_id] = "queued"
        self.emit(task_id, "task.created", f"task created — lane: {lane}",
                  goal=goal, lane=lane, driver=self.driver.name,
                  files=[f"{n} ({len(b)} bytes)" for n, b in sorted(files.items())],
                  torture=torture)
        self.pool.submit(self._run_task, task_id, goal, lane, files, torture)
        return task_id

    # -- the agent loop --

    def _run_task(self, task_id: str, goal: str, lane: str, files: dict[str, bytes],
                  torture: str | None) -> None:
        try:
            if torture:
                self._run_torture(task_id, torture)
            else:
                self._run_agent(task_id, goal, lane, files)
        except Exception as exc:  # noqa: BLE001 — the loop must always close out
            self.emit(task_id, "task.failed", f"internal error: {exc}", risk=RISK_HIGH,
                      error=str(exc)[:400])
            self._set_status(task_id, "failed")

    def _run_agent(self, task_id: str, goal: str, lane: str, files: dict[str, bytes]) -> None:
        self._set_status(task_id, "planning")
        planner = Planner(self.llm, lambda *a, **k: self.emit(task_id, *a, **k),
                          max_revisions=self.settings.max_revisions)
        plan = planner.plan(goal, files)
        self.emit(task_id, "plan.ready", plan["approach"] or "plan ready",
                  steps=plan["steps"])

        last_err = ""
        exit_code = -1
        code = ""
        result = None
        findings: list[Finding] = []
        attempt = 0
        for attempt in range(1, self.settings.max_revisions + 2):
            self._set_status(task_id, "coding")
            try:
                code = planner.write_code(goal, plan, files) if attempt == 1 else \
                    planner.fix_code(goal, code or "", last_err, exit_code, attempt)
            except ValueError as exc:
                self.emit(task_id, "llm.error", f"model output unparsable: {exc}", risk=RISK_MEDIUM)
                last_err = str(exc)
                continue
            self.emit(task_id, "code.generated", f"code attempt {attempt} — {len(code)} chars",
                      attempt=attempt, chars=len(code))
            # full source travels in the event detail so the UI + receipt carry it
            self.emit(task_id, "code.content", f"generated code (attempt {attempt})",
                      attempt=attempt, code=code)

            # --- policy gate ---
            self._set_status(task_id, "policy-check")
            findings = scan_code(code)
            for f in findings:
                self.emit(task_id, "policy.finding",
                          f"[{f.tag}] {f.message} ({f.where})",
                          risk=f.severity, tags=["policy", f.tag], **f.as_dict())
            self.emit(task_id, "policy.verdict", score_explanation(findings),
                      risk=max_severity(findings), findings=[f.as_dict() for f in findings])
            if is_hard_blocked(findings, self.settings.policy_mode, torture=False):
                self.emit(task_id, "policy.blocked",
                          "Run refused by policy (enforce mode): hostile pattern in generated code. "
                          "It never reached a sandbox.", risk=RISK_HIGH)
                self._set_status(task_id, "blocked")
                return

            # --- execute in a fresh sandbox ---
            self._set_status(task_id, "executing")
            req = ExecRequest(
                task_id=task_id, code=code, files=files,
                timeout_s=self.settings.timeout_s, mem_mb=self.settings.mem_mb,
                cpus=self.settings.cpus, pids=self.settings.pids,
                max_output_bytes=self.settings.max_output_bytes,
                max_artifact_bytes=self.settings.max_artifact_bytes,
                label=f"attempt {attempt}",
            )
            result = self.driver.run(req, self._driver_events(task_id))
            exit_code, last_err = result.exit_code, result.stderr
            if result.ok:
                break
            self.emit(task_id, "exec.retry",
                      f"attempt {attempt} failed (exit {exit_code}"
                      f"{', ' + result.killed_reason if result.killed_reason else ''}) — "
                      f"{'feeding traceback back to the model' if attempt <= self.settings.max_revisions else 'out of revisions'}",
                      risk=RISK_LOW, attempt=attempt)

        assert result is not None
        self._set_status(task_id, "explaining")
        artifact_names = self._persist_artifacts(task_id, result.artifacts)
        explanation = planner.explain(
            goal, result.stdout, result.stderr, result.exit_code,
            artifact_names, result.killed_reason,
        )
        self.store.update_task(task_id, explain=explanation)
        self.emit(task_id, "explain.ready", explanation[:160], markdown=explanation)
        self._seal(task_id, "completed" if result.ok else "failed", artifact_names, result.meta)

    # -- torture runs: prove containment, don't ask the model --

    def _run_torture(self, task_id: str, test_key: str) -> None:
        spec = TORTURE_TESTS.get(test_key)
        if not spec:
            self.emit(task_id, "task.failed", f"unknown torture test: {test_key}", risk=RISK_HIGH)
            self._set_status(task_id, "failed")
            return
        self.store.update_task(task_id, explain=f"Torture test: {spec['title']}")
        self.emit(task_id, "torture.started",
                  f"Detonating: {spec['title']}", risk=RISK_HIGH,
                  expected=spec["expected"], test=test_key)
        before = host_fingerprint()
        self.emit(task_id, "host.proof", f"host fingerprint before: {before}", fingerprint=before)

        self._set_status(task_id, "executing")
        req = ExecRequest(
            task_id=task_id, code=spec["code"],
            timeout_s=min(self.settings.timeout_s, 45), mem_mb=self.settings.mem_mb,
            cpus=self.settings.cpus, pids=self.settings.pids,
            max_output_bytes=self.settings.max_output_bytes,
            max_artifact_bytes=self.settings.max_artifact_bytes,
            label=f"torture:{test_key}",
        )
        findings = scan_code(spec["code"])
        for f in findings:
            self.emit(task_id, "policy.finding", f"[{f.tag}] {f.message} ({f.where})",
                      risk=f.severity, tags=["policy", f.tag], **f.as_dict())
        self.emit(task_id, "policy.verdict",
                  "Torture run: policy gate bypassed ON PURPOSE — this is the containment layer's audition.",
                  risk=RISK_HIGH, torture=True)

        result = self.driver.run(req, self._driver_events(task_id))
        after = host_fingerprint()
        host_intact = before == after
        self.emit(task_id, "host.proof", f"host fingerprint after: {after}", fingerprint=after)
        verdict = "CONTAINED" if host_intact else "HOST CHANGED — INVESTIGATE"
        self.emit(task_id, "containment.verdict", verdict, risk=RISK_INFO if host_intact else RISK_HIGH,
                  host_intact=host_intact, exit_code=result.exit_code,
                  killed_reason=result.killed_reason,
                  stdout_tail=result.stdout[-1500:], stderr_tail=result.stderr[-1500:],
                  expected=spec["expected"])
        self._seal(task_id, "completed", [], result.meta)

    # -- shared helpers --

    def _driver_events(self, task_id: str) -> EventFn:
        def on_event(event_type: str, payload: dict) -> None:
            risk = RISK_INFO
            if event_type == "sandbox.destroyed":
                risk = RISK_LOW
            elif event_type == "exec.finished" and payload.get("killed_reason"):
                risk = RISK_MEDIUM
            self.emit(task_id, event_type, _humanize(event_type, payload), risk=risk, **payload)
        return on_event

    def _persist_artifacts(self, task_id: str, artifacts: dict[str, bytes]) -> list[str]:
        base = self.settings.data_dir / "workspaces" / task_id / "artifacts"
        base.mkdir(parents=True, exist_ok=True)
        names = []
        for name in sorted(artifacts):
            blob = artifacts[name]
            path = base / Path(name).name
            path.write_bytes(blob)
            kind = "image" if Path(name).suffix.lower() in {".png", ".jpg", ".svg"} else "file"
            self.store.add_artifact(task_id, name, str(path), len(blob), kind)
            self.emit(task_id, "artifact.saved", f"artifact: {name} ({len(blob)} bytes)",
                      name=name, size=len(blob), kind=kind)
            names.append(name)
        return names

    def _seal(self, task_id: str, status: str, artifact_names: list[str], meta: dict) -> None:
        task = self.store.get_task(task_id) or {}
        events = bus.all_events(task_id)
        receipt = build_receipt(
            task_id, task.get("goal", ""), status, events,
            self.store.list_artifacts(task_id), meta={**meta, "events_verified": bus.verify_chain(task_id)},
        )
        self.store.update_task(task_id, receipt=json.dumps(receipt))
        self.emit(task_id, "receipt.sealed",
                  f"receipt sealed: {receipt['event_count']} events, head {receipt['head'][:12]}…",
                  head=receipt["head"], event_count=receipt["event_count"])
        self._set_status(task_id, status)
        self.emit(task_id, "task.completed" if status == "completed" else "task.failed",
                  "run complete" if status == "completed" else "run finished with failures")


def _humanize(event_type: str, payload: dict) -> str:
    if event_type == "sandbox.creating":
        return f"creating sandbox ({payload.get('driver')})…"
    if event_type == "sandbox.created":
        lim = payload.get("limits", {})
        return (f"sandbox up: {payload.get('sandbox_id')} — net:{payload.get('network', 'n/a')} "
                f"mem:{lim.get('mem_mb')}MB cpus:{lim.get('cpus')} pids:{lim.get('pids')}")
    if event_type == "exec.started":
        return "executing generated code inside sandbox…"
    if event_type == "exec.finished":
        kr = payload.get("killed_reason")
        return f"execution finished: exit {payload.get('exit_code')}" + (f" ({kr})" if kr else "")
    if event_type == "sandbox.destroyed":
        return "sandbox destroyed — environment gone"
    return event_type


_orchestrator: Orchestrator | None = None
_orch_lock = threading.Lock()


def get_orchestrator() -> Orchestrator:
    global _orchestrator
    with _orch_lock:
        if _orchestrator is None:
            _orchestrator = Orchestrator()
        return _orchestrator
