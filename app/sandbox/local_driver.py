"""Local subprocess driver — development convenience on machines without Docker.

It follows the same lifecycle contract as the Docker driver (fresh workspace,
caps, destroy after run) but the isolation is process-level only, NOT a real
containment boundary. The UI labels it clearly. Production containment is the
Docker driver on the Vultr VM.
"""
from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from .base import EventFn, ExecRequest, ExecResult, SandboxDriver


def _kill_tree(pid: int) -> None:
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                       capture_output=True, check=False)
    else:
        try:
            os.killpg(os.getpgid(pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


class LocalDriver(SandboxDriver):
    name = "local-subprocess"

    def run(self, req: ExecRequest, on_event: EventFn) -> ExecResult:
        ws = Path(tempfile.mkdtemp(prefix=f"airlock-{req.task_id[:8]}-"))
        on_event("sandbox.created", {
            "driver": self.name, "sandbox_id": ws.name, "workspace": str(ws),
            "limits": {"timeout_s": req.timeout_s, "mem_mb": req.mem_mb,
                       "cpus": req.cpus, "pids": req.pids},
            "note": "dev driver: process-level isolation only",
        })
        started = time.time()
        try:
            for name, blob in req.files.items():
                target = ws / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(blob)
            main = ws / "__airlock_main.py"
            main.write_text(req.code, encoding="utf-8")

            env = {
                "PATH": "/usr/bin:/bin" if os.name != "nt" else os.environ.get("PATH", ""),
                "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),  # python needs it on win
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONUNBUFFERED": "1",
                "HOME": str(ws),
                "TMPDIR": str(ws / "tmp"),
            }
            (ws / "tmp").mkdir(exist_ok=True)

            on_event("exec.started", {"driver": self.name, "entry": "__airlock_main.py"})
            popen_kwargs: dict = {}
            if os.name != "nt":
                popen_kwargs["start_new_session"] = True
            proc = subprocess.Popen(
                [sys.executable, "-I", str(main)],
                cwd=str(ws), env=env,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                errors="replace", **popen_kwargs,
            )
            killed_reason = None
            try:
                stdout, stderr = proc.communicate(timeout=req.timeout_s)
            except subprocess.TimeoutExpired:
                killed_reason = "timeout"
                _kill_tree(proc.pid)
                stdout, stderr = proc.communicate()
            duration = time.time() - started

            stdout, stderr = self._cap(stdout, req.max_output_bytes), self._cap(stderr, req.max_output_bytes)
            artifacts = self._collect_artifacts(ws, req)
            on_event("exec.finished", {
                "exit_code": proc.returncode, "duration_s": round(duration, 2),
                "killed_reason": killed_reason,
                "stdout_tail": stdout[-2000:], "stderr_tail": stderr[-2000:],
            })
            return ExecResult(
                exit_code=proc.returncode if proc.returncode is not None else -1,
                stdout=stdout, stderr=stderr, artifacts=artifacts,
                duration_s=duration, killed_reason=killed_reason,
                meta={"driver": self.name, "sandbox_id": ws.name},
            )
        finally:
            shutil.rmtree(ws, ignore_errors=True)
            on_event("sandbox.destroyed", {"driver": self.name, "workspace_removed": True})

    def _cap(self, text: str, limit: int) -> str:
        data = text.encode("utf-8", errors="replace")
        if len(data) <= limit:
            return text
        return data[:limit].decode("utf-8", errors="ignore") + "\n...[output capped]"

    def _collect_artifacts(self, ws: Path, req: ExecRequest) -> dict[str, bytes]:
        artifacts: dict[str, bytes] = {}
        for path in sorted(ws.rglob("*")):
            if not path.is_file() or path.name == "__airlock_main.py":
                continue
            rel = path.relative_to(ws).as_posix()
            if rel.startswith("tmp"):
                continue
            try:
                if path.stat().st_size > req.max_artifact_bytes:
                    artifacts[rel] = f"[artifact {rel} exceeds {req.max_artifact_bytes} bytes]".encode()
                else:
                    artifacts[rel] = path.read_bytes()
            except OSError:
                continue
        return artifacts
