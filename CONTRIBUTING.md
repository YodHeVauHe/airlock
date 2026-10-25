# Contributing to Airlock

Thanks for your interest in making Airlock better. This document tells you how to get a
development environment running in five minutes, how the codebase is organized, and — because
this project is about containment — which rules are **non-negotiable**.

## The short version

1. Fork, branch, code, test, open a pull request.
2. Every change that touches execution, isolation, or policy needs a test that proves it.
3. Never weaken a containment invariant (see [Containment invariants](#containment-invariants))
   — not for convenience, not for a demo, not for speed.
4. Found a sandbox escape or a way to leak secrets? **Do not open a public issue.** See
   [SECURITY.md](SECURITY.md).

## Development setup

Requirements: Python 3.12+ (3.14 verified), git. Docker is **not** needed — the entire test
suite and the full product run against the offline mock planner and the `local` sandbox driver.

```bash
git clone https://github.com/YodHeVauHe/airlock.git
cd airlock
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m pytest          # 18 tests, offline, ~30 seconds
```

Run the app:

```bash
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
# open http://127.0.0.1:8000 — mock mode, no credentials needed
```

Detonate something at `http://127.0.0.1:8000/torture` — if the host fingerprint ever changes,
that's a bug we want to hear about immediately.

To test against the real planner, set `AIRLOCK_INFERENCE_API_KEY` + `AIRLOCK_INFERENCE_MODEL`
(see `.env.example`). CI never uses real keys, and neither should your PRs — the mock path is
part of the contract.

## How the codebase is organized

Read [docs/design.md](docs/design.md) for the full picture. The two-minute orientation:

| Path | Responsibility |
|---|---|
| `app/main.py` | FastAPI routes, SSE live stream |
| `app/orchestrator.py` | Task lifecycle: plan → code → policy → execute → explain → receipt. Torture runs and host fingerprints live here |
| `app/planner.py` | The reasoning loop's prompts and JSON parsing |
| `app/llm.py` | Vultr Serverless Inference client + the offline mock |
| `app/policy.py` | Pre-execution code scan, risk scoring, enforce mode |
| `app/sandbox/` | Drivers: `docker_driver.py` (production containment), `local_driver.py` (dev), `vultr_driver.py` (throwaway VMs) |
| `app/events.py` | Hash-chained event log + live bus |
| `app/receipts.py` | Receipt build/verify — tamper-evidence lives here |
| `sandbox/Dockerfile` | The disposable cell image |
| `tests/` | The contract. If behavior changes without a test change, the PR is incomplete |

## Containment invariants

These four are the product. A pull request that weakens any of them will be rejected, however
small the change looks:

1. **Process isolation** — agent code never executes in the control-plane process. The sandbox
   is a separate boundary (container, subprocess, or VM), never an import.
2. **Secret hygiene** — `AIRLOCK_INFERENCE_API_KEY`, `VULTR_API_KEY`, and every other
   credential stay in the control plane. Sandbox environments are built from scratch; env is
   never passed through. No key may ever be baked into `sandbox/` images.
3. **Resource limits** — every execution has a wall-clock timeout and memory/CPU/PID caps,
   enforced by the driver, not by the agent's good behavior.
4. **Lifecycle discipline** — every sandbox is destroyed after its task, on every code path,
   including timeouts and exceptions. Destruction is a first-class event.

If your change could affect these — anything in `app/sandbox/`, `app/policy.py`,
`app/orchestrator.py`, `sandbox/Dockerfile`, or the deploy files — say so explicitly in the PR
description and add a test in the spirit of `tests/test_lifecycle.py::test_timeout_is_killed_and_destroyed`.

## Testing expectations

- **Bug fixes**: include a failing test first, then the fix. The test name should describe the
  behavior, not the ticket.
- **New features**: tests covering the happy path and at least one failure path.
- **Keep the suite offline.** Tests must pass with no network, no Docker, and no API keys
  (`mock_llm=True`, `driver="local"`). Mock-mode behaviors are load-bearing — the whole CI runs
  on them.
- Torture tests are executable documentation: if you add a containment guarantee, consider
  adding a torture test that proves it.

## Style

- Type hints on public functions; `dataclasses` over dict-shaped mystery objects.
- No new heavyweight dependencies without discussion — the control plane deliberately has six.
- Comments state constraints the code can't show ("env is built from scratch — never
  passthrough"), not narration.
- Frontend stays buildless: server-rendered Jinja2 + vanilla JS + SSE. If you find yourself
  reaching for npm, reconsider.
- Commit messages: imperative, one line that says why, not just what.

## Pull requests

- Small and focused beats large and sweeping. One behavior per PR.
- Fill out the PR template; for containment-adjacent changes include the threat-model note.
- Screenshots or a short clip for anything the user can see — Presentation is a judging
  criterion, and it shows here too.
- CI must be green before review.

## Reporting bugs and proposing features

Use the issue templates. Good bug reports include: what you ran, what you expected, what
happened instead, and the relevant slice of the event timeline (the receipt makes this easy —
attach it). Feature ideas are welcome, especially in these directions:

- Pattern B: the sandboxed browser lane (Playwright in a container)
- A gVisor driver for kernel-level isolation
- An egress allowlist proxy as an alternative to `--network none`
- Per-run resource reports in the blast-radius panel

## Licensing

By contributing, you agree that your contributions are licensed under the [MIT License](LICENSE).
