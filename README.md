# 🛰️ Airlock — blast-radius-zero agent execution on Vultr

**Give your AI agent real work. Keep your blast radius at zero.**

Airlock is a production-style web app that lets an AI agent perform real work — analyzing your
data, generating charts, fixing your files — with **every action contained inside a disposable
sandbox**: no network, no secrets, hard resource caps, destroyed after each task. Everything the
agent does is streamed live, risk-scored by a policy engine, and sealed into a **tamper-evident,
hash-chained receipt** you can download and verify.

> Built for **Vultr: Agent Rush Hackathon — Challenge 1: Blast Radius Zero**.
> An agent that only chats is a demo; an agent that executes *safely* is a product.

---

## Why Airlock

Nobody lets agents touch real infrastructure, because one hallucinated `rm -rf` or one prompt
injection away is your machine. Airlock flips containment from a hidden implementation detail
into **the product itself**:

- **Watch it prove itself.** The Torture Chamber detonates `rm -rf /`, fork bombs, secret
  exfiltration, and internet call-homes *on purpose* — inside the sandbox, on camera, with a
  host-fingerprint hash before and after each run. If the fingerprint ever changes, you'll see
  it in red. It never does.
- **Verifiable output, not vibes.** The agent's final explanation is generated *from the run's
  real stdout and artifacts*. Charts exist because code wrote them; numbers are real because
  pandas computed them (in mock mode, a stdlib analyst computes them).
- **Receipts.** Every run produces a downloadable receipt: a SHA-256 hash chain of every event.
  Anyone can verify nothing was added, removed, or edited after the fact.

## Architecture

```
Browser ──HTTP/SSE──► Control plane (FastAPI, Vultr VM)
                        │
                        ├─ Planner ──HTTPS──► Vultr Serverless Inference
                        │      ▲               (https://api.vultrinference.com/v1)
                        │      └─ real outputs
                        │
                        ├─ Orchestrator ── per-task sandbox, create → run → destroy
                        │      ├─ DockerDriver   prod: --network none, --cap-drop ALL,
                        │      │                 read-only rootfs, mem/cpu/pids caps
                        │      ├─ LocalDriver    dev: subprocess (clearly labeled)
                        │      └─ VultrDriver    experimental: a THROWAWAY Vultr VM per
                        │                        task via the Vultr API, then destroyed
                        ├─ Policy engine — pre-exec scan + blast-radius scoring
                        ├─ Receipts — hash-chained, downloadable, verifiable
                        └─ SQLite + per-task artifact store
```

**Flow:** goal + files → plan (Vultr Inference) → generated Python → policy scan → fresh
sandbox → real stdout/artifacts streamed live → on failure the traceback goes back to the model
(bounded retries) → final explanation from real outputs → **sandbox destroyed** → receipt sealed.

### Containment invariants

| Requirement | How Airlock does it |
|---|---|
| Process isolation | Agent code never runs in the control plane; the Docker driver runs it as unprivileged `uid 1000` in a sibling container with `--cap-drop ALL`, `no-new-privileges`, read-only rootfs |
| Secret hygiene | The sandbox environment is built from scratch (3 harmless vars). API keys never enter a sandbox — static analysis also blocks `os.environ` probes pre-execution |
| Resource limits | Wall-clock kill, `--memory`/`--cpus`/`--pids-limit`, output and artifact size caps |
| Lifecycle discipline | Every sandbox is created per task and destroyed in a `finally` block — even on timeout or crash. Destruction is a first-class event in the timeline |

## The Torture Chamber (the containment moment)

One click each, fully streamed and receipted like any real task:

| Weapon | What the sandbox absorbs |
|---|---|
| `rm -rf /` | Read-only rootfs + unprivileged user: the delete bounces off |
| fork bomb | `--pids-limit` ceiling absorbs the fan-out; run killed at the cap |
| env exfiltration | The sandbox env has nothing to steal — no keys exist inside |
| internet call-home | `--network none`: every connect fails fast; nothing leaves |

Each detonation ends with `CONTAINED` and a **host fingerprint unchanged** proof.

## Quick start (no cloud needed)

```bash
pip install -r requirements.txt
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
# open http://localhost:8000  — mock mode: full agent loop, zero credentials
```

Upload `samples/sales.csv`, ask *"which region has the highest average revenue? chart it"*,
watch the run live, download the receipt. Then open `/torture` and detonate something.

Run the tests:

```bash
python -m pytest        # 18 tests: policy, lifecycle, receipts, API, torture containment
```

## Production deployment (Vultr VM)

One command on a fresh Ubuntu VM:

```bash
bash deploy/setup-vm.sh https://github.com/YodHeVauHe/airlock.git
```

or paste `deploy/cloud-init.yml` as the Vultr Cloud-Init user data at deploy time.
Details in [deploy/DEPLOY.md](deploy/DEPLOY.md). Then set
`AIRLOCK_INFERENCE_API_KEY` + `AIRLOCK_INFERENCE_MODEL` in `.env` to switch the agent's
reasoning from mock mode to **Vultr Serverless Inference**.

### Throwaway Vultr VMs per task (stretch lane)

Set `VULTR_API_KEY` + `AIRLOCK_VULTR_DRIVER=1` and Airlock can dispatch each task to an entire
disposable Vultr instance via the Vultr API — booted by cloud-init, HMAC-reporting its real
output, **destroyed by the control plane in a `finally`**. The strongest possible answer to
"lifecycle discipline".

## Repository map

```
app/                    control plane (FastAPI)
  main.py               routes + SSE live stream
  orchestrator.py       task lifecycle, agent loop, torture runs, host proof
  planner.py            plan → write code → fix → explain (Vultr Inference)
  llm.py                Vultr Serverless Inference client + offline mock
  policy.py             pre-exec code scan, risk scoring, enforce mode
  events.py             hash-chained event log + live bus
  receipts.py           build/verify tamper-evident run receipts
  store.py              SQLite persistence
  sandbox/              drivers: docker | local | vultr-instance
  web/                  templates + static (no JS framework, no build step)
sandbox/Dockerfile      the disposable cell image (python + pandas + matplotlib)
deploy/                 compose, cloud-init, VM setup script, DEPLOY.md
samples/                sales.csv (demo data), broken.csv (file-fixer lane)
tests/                  18 tests incl. containment + receipt tamper-evidence
docs/design.md          the design document
```

## Judging map

- **Application of Technology** — Vultr VM hosts the control plane and all sandboxes; every LLM
  call goes through Vultr Serverless Inference; optional per-task throwaway instances via the
  Vultr API; Docker-based containment with four enforced invariants.
- **Presentation** — mission-control UI with a live hash-chained timeline and blast-radius
  panel; the safety story is visible, not hidden in a README.
- **Business Value** — "run untrusted AI agent work on your real data without risking your
  infrastructure": the missing trust layer between LLMs and production ops teams.
- **Originality** — torture chamber as a product feature, signed/verifiable run receipts,
  policy engine with blast-radius scoring, host fingerprint proof.

## License

MIT.
