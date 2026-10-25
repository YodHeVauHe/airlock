"""Airlock control plane — FastAPI app, routes, SSE live stream."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .config import get_settings
from .events import bus
from .orchestrator import TORTURE_TESTS, get_orchestrator
from .receipts import verify_receipt
from .sandbox import driver_health

app = FastAPI(title="Airlock", docs_url=None, redoc_url=None)

BASE_DIR = Path(__file__).parent
templates = Jinja2Templates(directory=str(BASE_DIR / "web" / "templates"))
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "web" / "static")), name="static")


def _orch():
    return get_orchestrator()


def _settings():
    return get_settings()


# ------------------------------------------------------------------ pages

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    tasks = _orch().store.list_tasks(limit=20)
    s = _settings()
    return templates.TemplateResponse(request, "index.html", {
        "tasks": tasks,
        "driver": s.driver,
        "llm_mode": "mock (no API key)" if s.llm_is_mock else "Vultr Serverless Inference",
        "policy_mode": s.policy_mode,
    })


@app.get("/task/{task_id}", response_class=HTMLResponse)
async def task_page(request: Request, task_id: str):
    task = _orch().store.get_task(task_id)
    if not task:
        raise HTTPException(404, "task not found")
    return templates.TemplateResponse(request, "task.html", {"task": task})


@app.get("/torture", response_class=HTMLResponse)
async def torture_page(request: Request):
    tests = [
        {"key": k, "title": v["title"], "expected": v["expected"]}
        for k, v in TORTURE_TESTS.items()
    ]
    recent = [t for t in _orch().store.list_tasks(limit=30) if t.get("torture")]
    return templates.TemplateResponse(request, "torture.html", {"tests": tests, "recent": recent})


# ------------------------------------------------------------------ api

@app.post("/api/tasks")
async def create_task(
    goal: str = Form(...),
    lane: str = Form("analyze"),
    files: list[UploadFile] = File(default=[]),
):
    goal = goal.strip()
    if not goal:
        raise HTTPException(400, "goal is required")
    blobs: dict[str, bytes] = {}
    for f in files[:5]:
        data = await f.read()
        if len(data) > 10 * 1024 * 1024:
            raise HTTPException(400, f"{f.filename} exceeds 10MB")
        if f.filename:
            blobs[Path(f.filename).name] = data
    if lane not in {"analyze", "fix", "chart"}:
        lane = "analyze"
    task_id = _orch().create_task(goal, lane, blobs)
    return {"task_id": task_id}


@app.get("/api/tasks")
async def list_tasks():
    return _orch().store.list_tasks(limit=50)


@app.get("/api/tasks/{task_id}")
async def task_detail(task_id: str):
    task = _orch().store.get_task(task_id)
    if not task:
        raise HTTPException(404, "task not found")
    task["artifacts"] = _orch().store.list_artifacts(task_id)
    task["verified"] = bus.verify_chain(task_id)
    return task


@app.get("/api/tasks/{task_id}/events")
async def task_events(task_id: str, after: int = 0):
    return [e.to_dict() for e in bus.history(task_id, after)]


@app.get("/api/tasks/{task_id}/stream")
async def task_stream(task_id: str):
    if not _orch().store.get_task(task_id):
        raise HTTPException(404, "task not found")

    async def gen():
        sub = bus.subscribe(task_id)
        try:
            # replay history, then follow live
            seq = 0
            heartbeat_deadline = asyncio.get_event_loop().time() + 15
            while True:
                pending = bus.history(task_id, seq)
                for ev in pending:
                    yield f"data: {json.dumps(ev.to_dict())}\n\n"
                    seq = ev.seq
                if _orch().status(task_id) in {"completed", "failed", "blocked"} and not pending:
                    yield f"event: done\ndata: {{\"status\": \"{_orch().status(task_id)}\"}}\n\n"
                    return
                try:
                    ev = await asyncio.wait_for(asyncio.to_thread(sub.get, True, 0.5), timeout=2.0)
                    if ev.seq > seq:
                        yield f"data: {json.dumps(ev.to_dict())}\n\n"
                        seq = ev.seq
                except asyncio.TimeoutError:
                    if asyncio.get_event_loop().time() > heartbeat_deadline:
                        yield ": keepalive\n\n"
                        heartbeat_deadline = asyncio.get_event_loop().time() + 15
        finally:
            bus.unsubscribe(task_id, sub)

    return StreamingResponse(gen(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache", "X-Accel-Buffering": "no",
    })


@app.get("/api/tasks/{task_id}/artifacts/{name}")
async def artifact_download(task_id: str, name: str):
    for art in _orch().store.list_artifacts(task_id):
        if art["name"] == name:
            path = Path(art["path"])
            if path.is_file():
                media = "image/svg+xml" if path.suffix == ".svg" else (
                    "image/png" if path.suffix == ".png" else "application/octet-stream")
                return StreamingResponse(
                    iter([path.read_bytes()]),
                    media_type=media,
                    headers={"Content-Disposition": f'attachment; filename="{path.name}"'},
                )
    raise HTTPException(404, "artifact not found")


@app.get("/api/tasks/{task_id}/receipt")
async def task_receipt(task_id: str):
    task = _orch().store.get_task(task_id)
    if not task or not task.get("receipt"):
        raise HTTPException(404, "receipt not sealed yet")
    receipt = json.loads(task["receipt"])
    ok, reason = verify_receipt(receipt)
    receipt["verification"] = {"ok": ok, "reason": reason}
    return JSONResponse(receipt, headers={
        "Content-Disposition": f'attachment; filename="airlock-receipt-{task_id}.json"'})


@app.get("/api/tasks/{task_id}/receipt/verify")
async def task_receipt_verify(task_id: str):
    task = _orch().store.get_task(task_id)
    if not task or not task.get("receipt"):
        raise HTTPException(404, "receipt not sealed yet")
    ok, reason = verify_receipt(json.loads(task["receipt"]))
    return {"task_id": task_id, "ok": ok, "reason": reason}


@app.post("/api/torture/{test_key}")
async def run_torture(test_key: str):
    if test_key not in TORTURE_TESTS:
        raise HTTPException(404, "unknown torture test")
    task_id = _orch().create_task(f"Torture test: {TORTURE_TESTS[test_key]['title']}",
                                  lane="torture", files={}, torture=test_key)
    return {"task_id": task_id}


@app.post("/api/vultr-driver/callback")
async def vultr_callback(request: Request, instance: str):
    from .sandbox.vultr_driver import deliver_callback
    body = await request.json()
    signature = request.headers.get("X-Signature", "")
    orch = _orch()
    from .sandbox import get_driver
    driver = get_driver(orch.settings)
    secret = getattr(driver, "callback_secret", "")
    if deliver_callback(instance, body, signature, secret):
        return {"ok": True}
    raise HTTPException(403, "bad signature")


@app.get("/api/health")
async def health():
    s = _settings()
    return {
        "status": "ok",
        "driver": driver_health(s),
        "llm": "mock" if s.llm_is_mock else "vultr-serverless-inference",
        "policy_mode": s.policy_mode,
        "version": "0.1.0",
    }
