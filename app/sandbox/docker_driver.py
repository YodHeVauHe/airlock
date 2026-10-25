"""Docker driver — the production containment boundary on the Vultr VM.

Per-task container, built for zero blast radius:
  - ``--network none``            no egress at all (default)
  - ``--cap-drop ALL``            no kernel capabilities
  - ``--security-opt no-new-privileges``
  - ``--read-only`` rootfs, small exec-tmpfs
  - ``--memory``/``--cpus``/``--pids-limit``  hard resource ceilings
  - fresh workspace volume per run, removed afterwards
  - environment built from scratch: NO control-plane env, NO API keys
  - ``--rm`` + explicit ``docker rm -f`` in a finally block

The driver shells out to the docker CLI (present on the Vultr VM) rather than
pulling in the docker SDK — one less dependency inside the trust boundary.
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

from .base import EventFn, ExecRequest, ExecResult, SandboxDriver


class DockerDriver(SandboxDriver):
    name = "docker"

    def __init__(self, image: str = "airlock-sandbox:latest", network: str = "none") -> None:
        self.image = image
        self.network = network

    def _docker(self, *args: str, timeout: float = 60) -> subprocess.CompletedProcess:
        return subprocess.run(["docker", *args], capture_output=True, text=True, timeout=timeout)

    def run(self, req: ExecRequest, on_event: EventFn) -> ExecResult:
        cid = f"airlock-sb-{uuid.uuid4().hex[:12]}"
        ws = Path(tempfile.mkdtemp(prefix=f"airlock-{req.task_id[:8]}-"))
        on_event("sandbox.creating", {"driver": self.name, "sandbox_id": cid, "image": self.image})
        started = time.time()
        container_created = False
        try:
            for name, blob in req.files.items():
                target = ws / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(blob)
            main = ws / "__airlock_main.py"
            main.write_text(req.code, encoding="utf-8")
            # the container runs as unprivileged uid 1000; the workspace must be writable
            ws.chmod(0o777)
            for p in ws.rglob("*"):
                try:
                    p.chmod(0o666 if p.is_file() else 0o777)
                except OSError:
                    pass

            create = [
                "docker", "run",
                "--name", cid,
                "--rm",
                "--network", self.network,
                "--memory", f"{req.mem_mb}m",
                "--memory-swap", f"{req.mem_mb}m",
                "--cpus", str(req.cpus),
                "--pids-limit", str(req.pids),
                "--read-only",
                "--tmpfs", "/tmp:size=64m",
                "--cap-drop", "ALL",
                "--security-opt", "no-new-privileges",
                "--user", "1000:1000",
                "-e", "PYTHONDONTWRITEBYTECODE=1",
                "-e", "PYTHONUNBUFFERED=1",
                "-e", "HOME=/workspace",
                "-e", "TMPDIR=/tmp",
                "-v", f"{ws}:/workspace",
                "-w", "/workspace",
                "--entrypoint", "python",
                self.image,
                "-I", "/workspace/__airlock_main.py",
            ]
            proc = subprocess.Popen(
                create, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, errors="replace",
            )
            container_created = True
            on_event("sandbox.created", {
                "driver": self.name, "sandbox_id": cid, "image": self.image,
                "network": self.network,
                "limits": {"timeout_s": req.timeout_s, "mem_mb": req.mem_mb,
                           "cpus": req.cpus, "pids": req.pids,
                           "rootfs": "read-only", "capabilities": "none"},
            })
            on_event("exec.started", {"driver": self.name, "entry": "runner.py"})
            try:
                stdout, stderr = proc.communicate(timeout=req.timeout_s)
                killed_reason = None
            except subprocess.TimeoutExpired:
                killed_reason = "timeout"
                subprocess.run(["docker", "kill", cid], capture_output=True, timeout=30)
                stdout, stderr = proc.communicate()
            duration = time.time() - started
            exit_code = proc.returncode if proc.returncode is not None else -1
            if killed_reason:
                exit_code = 137

            stdout = _cap(stdout, req.max_output_bytes)
            stderr = _cap(stderr, req.max_output_bytes)
            artifacts = self._collect_artifacts(ws, req)

            on_event("exec.finished", {
                "exit_code": exit_code, "duration_s": round(duration, 2),
                "killed_reason": killed_reason,
                "stdout_tail": stdout[-2000:], "stderr_tail": stderr[-2000:],
            })
            return ExecResult(
                exit_code=exit_code, stdout=stdout, stderr=stderr, artifacts=artifacts,
                duration_s=duration, killed_reason=killed_reason,
                meta={"driver": self.name, "sandbox_id": cid, "image": self.image,
                      "network": self.network},
            )
        finally:
            if container_created:
                subprocess.run(["docker", "rm", "-f", cid], capture_output=True, timeout=30)
            shutil.rmtree(ws, ignore_errors=True)
            on_event("sandbox.destroyed", {"driver": self.name, "workspace_removed": True,
                                           "sandbox_id": cid})

    def _collect_artifacts(self, ws: Path, req: ExecRequest) -> dict[str, bytes]:
        artifacts: dict[str, bytes] = {}
        for path in sorted(ws.rglob("*")):
            if not path.is_file() or path.name == "__airlock_main.py":
                continue
            rel = path.relative_to(ws).as_posix()
            try:
                if path.stat().st_size > req.max_artifact_bytes:
                    artifacts[rel] = f"[artifact {rel} exceeds {req.max_artifact_bytes} bytes]".encode()
                else:
                    artifacts[rel] = path.read_bytes()
            except OSError:
                continue
        return artifacts


def _cap(text: str, limit: int) -> str:
    data = text.encode("utf-8", errors="replace")
    if len(data) <= limit:
        return text
    return data[:limit].decode("utf-8", errors="ignore") + "\n...[output capped]"
