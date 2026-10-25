import time

from fastapi.testclient import TestClient

import app.main as main_mod
from app.config import Settings
from app.orchestrator import Orchestrator
from app.store import Store


def make_client(tmp_path):
    settings = Settings(data_dir=tmp_path / "data", driver="local", mock_llm=True, timeout_s=20)
    settings.ensure_dirs()
    orch = Orchestrator(settings=settings, store=Store(settings.data_dir / "test.db"))

    main_mod.get_orchestrator = lambda: orch
    client = TestClient(main_mod.app)
    return client, orch, None


def wait(orch, task_id, timeout=60):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if orch.status(task_id) in {"completed", "failed", "blocked"}:
            return orch.status(task_id)
        time.sleep(0.2)
    raise TimeoutError(orch.status(task_id))


def test_health_and_pages(tmp_path):
    client, orch, _ = make_client(tmp_path)
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["llm"] == "mock"
    for page in ["/", "/torture"]:
        assert client.get(page).status_code == 200


def test_full_api_flow_with_upload(tmp_path):
    client, orch, _ = make_client(tmp_path)
    r = client.post("/api/tasks",
                    data={"goal": "analyze this", "lane": "analyze"},
                    files={"files": ("data.csv", b"a,b\n1,2\n3,4\n", "text/csv")})
    assert r.status_code == 200
    task_id = r.json()["task_id"]

    detail = client.get(f"/api/tasks/{task_id}").json()
    assert detail["status"] in {"queued", "planning", "coding", "executing", "explaining"}

    status = wait(orch, task_id)
    assert status == "completed"

    # events endpoint
    events = client.get(f"/api/tasks/{task_id}/events").json()
    assert len(events) > 5
    assert events[-1]["seq"] == len(events)

    # receipt
    receipt = client.get(f"/api/tasks/{task_id}/receipt").json()
    assert receipt["verification"]["ok"] is True

    # artifacts downloadable
    arts = client.get(f"/api/tasks/{task_id}").json()["artifacts"]
    if arts:
        dl = client.get(f"/api/tasks/{task_id}/artifacts/{arts[0]['name']}")
        assert dl.status_code == 200
        assert len(dl.content) == arts[0]["size"]

    # task page renders
    assert client.get(f"/task/{task_id}").status_code == 200


def test_torture_endpoint(tmp_path):
    client, orch, _ = make_client(tmp_path)
    r = client.post("/api/torture/env-probe")
    assert r.status_code == 200
    task_id = r.json()["task_id"]
    wait(orch, task_id)
    events = client.get(f"/api/tasks/{task_id}/events").json()
    assert any(e["type"] == "containment.verdict" for e in events)
    verdict = next(e for e in events if e["type"] == "containment.verdict")
    assert verdict["detail"]["host_intact"] is True


def test_unknown_task_404(tmp_path):
    client, _, _ = make_client(tmp_path)
    assert client.get("/api/tasks/nope").status_code == 404
    assert client.get("/api/tasks/nope/receipt").status_code == 404
