import json
import time

from app.config import Settings
from app.events import bus
from app.orchestrator import Orchestrator, TORTURE_TESTS, host_fingerprint
from app.receipts import build_receipt, verify_receipt
from app.store import Store


def make_orch(tmp_path, **overrides) -> Orchestrator:
    kwargs = dict(
        data_dir=tmp_path / "data",
        driver="local",
        mock_llm=True,
        timeout_s=20,
        policy_mode="enforce",
    )
    kwargs.update(overrides)
    settings = Settings(**kwargs)
    settings.ensure_dirs()
    return Orchestrator(settings=settings, store=Store(settings.data_dir / "test.db"))


def wait_for_status(orch, task_id, statuses, timeout=60):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if orch.status(task_id) in statuses:
            return orch.status(task_id)
        time.sleep(0.2)
    raise TimeoutError(f"task {task_id} stuck at {orch.status(task_id)}")


def test_agent_run_analyze_lane(tmp_path):
    orch = make_orch(tmp_path)
    csv = b"region,sales\nnorth,10\nnorth,30\nsouth,5\n"
    task_id = orch.create_task("summarize sales by region", "analyze",
                               {"sales.csv": csv})
    status = wait_for_status(orch, task_id, {"completed", "failed", "blocked"})

    assert status == "completed"
    task = orch.store.get_task(task_id)
    assert task["explain"], "explanation should be filled from real outputs"
    events = bus.all_events(task_id)
    types = [e.type for e in events]
    # the full containment lifecycle happened
    assert "sandbox.created" in types
    assert "sandbox.destroyed" in types
    assert types.index("sandbox.created") < types.index("sandbox.destroyed")
    assert "receipt.sealed" in types
    # artifacts from the real run
    artifacts = orch.store.list_artifacts(task_id)
    names = {a["name"] for a in artifacts}
    assert "summary.csv" in names
    assert "chart.svg" in names
    # mock analyst prints its RESULT line
    exec_events = [e for e in events if e.type == "exec.finished"]
    assert exec_events and exec_events[-1].detail["exit_code"] == 0


def test_policy_block_in_enforce_mode(tmp_path):
    orch = make_orch(tmp_path)
    # force the mock to emit hostile code by monkeypatching the planner's writer
    from app.planner import Planner
    original = Planner.write_code

    def hostile(self, goal, plan, files):
        return "import os\nprint(os.environ.get('SECRET'))\n"

    Planner.write_code = hostile
    try:
        task_id = orch.create_task("steal secrets", "analyze", {})
        status = wait_for_status(orch, task_id, {"completed", "failed", "blocked"})
    finally:
        Planner.write_code = original
    assert status == "blocked"
    types = [e.type for e in bus.all_events(task_id)]
    assert "policy.blocked" in types
    assert "sandbox.created" not in types, "blocked code must never reach a sandbox"


def test_error_feedback_loop(tmp_path):
    """First attempt fails, model gets the traceback, second attempt succeeds."""
    orch = make_orch(tmp_path)
    from app.planner import Planner
    attempts = {"write": 0, "fix": 0}
    original_write, original_fix = Planner.write_code, Planner.fix_code

    def flaky_write(self, goal, plan, files):
        attempts["write"] += 1
        return "raise RuntimeError('boom on purpose')\n"

    def recover_fix(self, goal, code, stderr, exit_code, attempt):
        attempts["fix"] += 1
        return "print('recovered'); print('RESULT: ok')\n"

    Planner.write_code = flaky_write
    Planner.fix_code = recover_fix
    try:
        task_id = orch.create_task("do the thing", "analyze", {})
        status = wait_for_status(orch, task_id, {"completed", "failed", "blocked"})
    finally:
        Planner.write_code = original_write
        Planner.fix_code = original_fix
    assert status == "completed"
    types = [e.type for e in bus.all_events(task_id)]
    assert "exec.retry" in types
    assert attempts == {"write": 1, "fix": 1}
    # two sandboxes were created and BOTH destroyed (lifecycle discipline)
    assert types.count("sandbox.created") == 2
    assert types.count("sandbox.destroyed") == 2


def test_timeout_is_killed_and_destroyed(tmp_path):
    orch = make_orch(tmp_path, timeout_s=2)
    from app.planner import Planner
    original_write, original_fix = Planner.write_code, Planner.fix_code

    def endless(self, *args, **kwargs):
        return "print('sleeping'); import time; time.sleep(60)\n"

    Planner.write_code = endless
    Planner.fix_code = endless
    try:
        task_id = orch.create_task("never finishes", "analyze", {})
        status = wait_for_status(orch, task_id, {"completed", "failed", "blocked"}, timeout=60)
    finally:
        Planner.write_code = original_write
        Planner.fix_code = original_fix
    assert status == "failed"
    events = bus.all_events(task_id)
    exec_events = [e for e in events if e.type == "exec.finished"]
    assert exec_events, "at least one execution must have happened"
    assert exec_events[-1].detail["killed_reason"] == "timeout"
    types = [e.type for e in events]
    # every sandbox attempt was destroyed — lifecycle discipline holds on timeout
    assert types.count("sandbox.destroyed") == types.count("sandbox.created")
    assert types.count("sandbox.destroyed") >= 2


def test_torture_run_proves_containment(tmp_path):
    orch = make_orch(tmp_path, timeout_s=20)
    before = host_fingerprint()
    task_id = orch.create_task("Torture test: env-probe", "torture", {}, torture="env-probe")
    status = wait_for_status(orch, task_id, {"completed", "failed", "blocked"})
    assert status == "completed"
    assert host_fingerprint() == before, "host must be untouched by torture runs"
    events = bus.all_events(task_id)
    verdicts = [e for e in events if e.type == "containment.verdict"]
    assert verdicts and verdicts[0].detail["host_intact"] is True
    # env-probe: the sandbox env genuinely has no credential-shaped keys
    out = verdicts[0].detail["stdout_tail"]
    assert "NOTHING TO STEAL" in out


def test_receipt_is_tamper_evident(tmp_path):
    orch = make_orch(tmp_path)
    task_id = orch.create_task("make a receipt", "analyze", {"x.csv": b"a,b\n1,2\n"})
    wait_for_status(orch, task_id, {"completed", "failed", "blocked"})
    task = orch.store.get_task(task_id)
    receipt = json.loads(task["receipt"])
    ok, reason = verify_receipt(receipt)
    assert ok, reason
    # tamper with one event's title -> chain must break
    receipt["events"][0]["title"] = "evil rewrite"
    ok2, reason2 = verify_receipt(receipt)
    assert not ok2
