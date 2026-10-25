"""Vultr driver — a THROWAWAY cloud instance per task, via the Vultr API.

The strongest form of the challenge's "Lifecycle discipline": the sandbox is
not a container on the control plane's machine but an entire disposable VM.
The instance boots with cloud-init that runs the task, posts the result back
(HMAC-signed), and the control plane ALWAYS destroys the instance afterwards.

Status: experimental (flag AIRLOCK_VULTR_DRIVER=1 + VULTR_API_KEY). Boot adds
roughly a minute, so the Docker driver remains the default lane.

Secret hygiene holds here too: the instance receives the task bundle and a
run-scoped HMAC key only — never the Vultr API key, which lives in the
control plane and is used solely to create/destroy instances.
"""
from __future__ import annotations

import base64
import gzip
import hashlib
import hmac
import json
import secrets
import threading
import time
import uuid

import httpx

from .base import EventFn, ExecRequest, ExecResult, SandboxDriver

VULTR_API = "https://api.vultr.com/v2"

# set by the FastAPI callback route when an instance reports its result
_callbacks: dict[str, threading.Event] = {}
_results: dict[str, dict] = {}


def deliver_callback(instance_id: str, body: dict, signature: str, secret: str) -> bool:
    mac = hmac.new(secret.encode(), json.dumps(body, sort_keys=True).encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(mac, signature):
        return False
    _results[instance_id] = body
    ev = _callbacks.get(instance_id)
    if ev:
        ev.set()
    return True


class VultrInstanceDriver(SandboxDriver):
    name = "vultr-instance"

    def __init__(self, api_key: str, region: str, plan: str, callback_secret: str,
                 public_url: str, boot_timeout_s: int = 240) -> None:
        self.api_key = api_key
        self.region = region
        self.plan = plan
        self.callback_secret = callback_secret
        self.public_url = public_url.rstrip("/")
        self.boot_timeout_s = boot_timeout_s

    def _api(self, method: str, path: str, json_body: dict | None = None) -> dict:
        r = httpx.request(
            method, f"{VULTR_API}{path}",
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            json=json_body, timeout=30,
        )
        if r.status_code >= 400:
            raise RuntimeError(f"vultr api {method} {path} -> {r.status_code}: {r.text[:200]}")
        return r.json() if r.text else {}

    def _user_data(self, req: ExecRequest, instance_ref: str, run_key: str) -> str:
        bundle = base64.b64encode(
            gzip.compress(json.dumps({
                "code": req.code,
                "files": {k: base64.b64encode(v).decode() for k, v in req.files.items()},
                "timeout_s": req.timeout_s,
                "max_output_bytes": req.max_output_bytes,
                "max_artifact_bytes": req.max_artifact_bytes,
            }).encode()).decode()
        )
        script = f"""#!/bin/bash
set -u
BUNDLE_DIR=/opt/airlock
mkdir -p $BUNDLE_DIR
echo '{bundle}' > $BUNDLE_DIR/bundle.b64
python3 - <<'PYEOF'
import base64, gzip, json, os, subprocess, sys, time

work = "/opt/airlock"
spec = json.loads(gzip.decompress(base64.b64decode(open(work + "/bundle.b64").read())))
ws = os.path.join(work, "workspace")
os.makedirs(ws + "/tmp", exist_ok=True)
os.chdir(ws)
for name, blob in spec["files"].items():
    path = os.path.join(ws, name)
    os.makedirs(os.path.dirname(path) or ws, exist_ok=True)
    open(path, "wb").write(base64.b64decode(blob))
open(ws + "/__airlock_main.py", "w").write(spec["code"])

env = {{"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": ws, "TMPDIR": ws + "/tmp",
        "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUNBUFFERED": "1"}}
import resource
def caps():
    b = spec["max_output_bytes"]
    resource.setrlimit(resource.RLIMIT_FSIZE, (spec["max_artifact_bytes"] * 4, spec["max_artifact_bytes"] * 4))
    resource.setrlimit(resource.RLIMIT_CPU, (spec["timeout_s"] * 2, spec["timeout_s"] * 2))
started = time.time()
p = subprocess.Popen([sys.executable, "-I", ws + "/__airlock_main.py"], cwd=ws, env=env,
                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                     errors="replace", preexec_fn=caps)
try:
    out, err = p.communicate(timeout=spec["timeout_s"])
    killed = None
except subprocess.TimeoutExpired:
    p.kill(); out, err = p.communicate(); killed = "timeout"
duration = time.time() - started

artifacts = {{}}
for root, _dirs, names in os.walk(ws):
    for n in names:
        if n == "__airlock_main.py":
            continue
        path = os.path.join(root, n)
        rel = os.path.relpath(path, ws)
        if os.path.getsize(path) <= spec["max_artifact_bytes"]:
            artifacts[rel] = base64.b64encode(open(path, "rb").read()).decode()

body = {{"instance_ref": "{instance_ref}", "exit_code": p.returncode if p.returncode is not None else -1,
        "stdout": out[-spec["max_output_bytes"]:], "stderr": err[-spec["max_output_bytes"]:],
        "duration_s": round(duration, 2), "killed_reason": killed, "artifacts": artifacts}}
import urllib.request
payload = json.dumps(body, sort_keys=True).encode()
sig = hmac.new(b"{run_key}", payload, hashlib.sha256).hexdigest()
req = urllib.request.Request("{self.public_url}/api/vultr-driver/callback?instance={instance_ref}",
                             data=payload, headers={{"Content-Type": "application/json", "X-Signature": sig}})
urllib.request.urlopen(req, timeout=15)
PYEOF
"""
        return script

    def run(self, req: ExecRequest, on_event: EventFn) -> ExecResult:
        instance_ref = f"airlock-{uuid.uuid4().hex[:8]}"
        run_key = secrets.token_hex(32)
        on_event("sandbox.creating", {
            "driver": self.name, "sandbox_id": instance_ref,
            "region": self.region, "plan": self.plan,
            "note": "throwaway Vultr instance per task — destroyed afterwards",
        })
        label = f"airlock-sandbox {instance_ref}"
        user_data = self._user_data(req, instance_ref, run_key)
        created = self._api("POST", "/instances", {
            "region": self.region,
            "plan": self.plan,
            "os_id": 1743,  # Ubuntu 24.04 x64
            "label": label[:32],
            "hostname": instance_ref[:32],
            "backups": "disabled",
            "enable_ipv6": False,
            "user_data": base64.b64encode(user_data.encode()).decode(),
            "firewall_group_id": "",
        })
        instance_id = created["instance"]["id"]
        instance_ip = created["instance"].get("main_ip", "")
        on_event("sandbox.created", {
            "driver": self.name, "sandbox_id": instance_ref, "vultr_instance_id": instance_id,
            "region": self.region, "plan": self.plan, "ip": instance_ip,
        })

        done = threading.Event()
        _callbacks[instance_ref] = done
        _results.pop(instance_ref, None)
        started = time.time()
        destroyed = False

        def destroy() -> None:
            nonlocal destroyed
            if not destroyed:
                try:
                    self._api("DELETE", f"/instances/{instance_id}")
                except Exception:
                    pass
                destroyed = True

        try:
            # wait for the instance to report (cloud-init boot + run)
            deadline = self.boot_timeout_s + req.timeout_s + 30
            if not done.wait(timeout=deadline):
                on_event("exec.finished", {"exit_code": -1, "killed_reason": "timeout",
                                           "duration_s": round(time.time() - started, 2)})
                return ExecResult(exit_code=-1, stdout="", stderr="[vultr driver] instance never reported",
                                  duration_s=time.time() - started, killed_reason="timeout",
                                  meta={"driver": self.name, "sandbox_id": instance_ref,
                                        "vultr_instance_id": instance_id})
            body = _results.pop(instance_ref)
            artifacts = {k: base64.b64decode(v) for k, v in body.get("artifacts", {}).items()}
            on_event("exec.finished", {
                "exit_code": body.get("exit_code"), "duration_s": body.get("duration_s"),
                "killed_reason": body.get("killed_reason"),
                "stdout_tail": str(body.get("stdout", ""))[-2000:],
                "stderr_tail": str(body.get("stderr", ""))[-2000:],
            })
            return ExecResult(
                exit_code=body.get("exit_code", -1),
                stdout=body.get("stdout", ""), stderr=body.get("stderr", ""),
                artifacts=artifacts, duration_s=body.get("duration_s", 0.0),
                killed_reason=body.get("killed_reason"),
                meta={"driver": self.name, "sandbox_id": instance_ref,
                      "vultr_instance_id": instance_id},
            )
        finally:
            destroy()
            _callbacks.pop(instance_ref, None)
            on_event("sandbox.destroyed", {"driver": self.name, "sandbox_id": instance_ref,
                                           "vultr_instance_id": instance_id,
                                           "vultr_instance_destroyed": True})
