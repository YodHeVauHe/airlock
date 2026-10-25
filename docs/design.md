# Airlock — Blast-Radius-Zero Agent Execution on Vultr

**Design doc · 2026-10-25 · Vultr: Agent Rush Hackathon, Challenge 1 "Blast Radius Zero"**

> Working autonomously per Hilda's instruction: "the goal is to brainstorm and work until you
> succeed." Approaches were weighed and one chosen (below). Any call can be overridden — the
> architecture isolates those choices behind small interfaces.

## Intent and why

Vultr's brief: *"Build a web-based agent that performs real work — writing and running code,
or operating a real browser — with every action contained inside a sandbox running on Vultr."*

Agents that only chat are demos; agents that execute are products — but nobody lets an agent
touch real infrastructure or data, because the blast radius of a mistake (or a prompt
injection) is the user's own machine. **Airlock makes containment the product.** Users hand the
agent real work — analyze this CSV, fix this file, chart this data — and Airlock proves, live,
that the work happened inside a disposable cell on Vultr: every action streamed, risk-scored,
and destroyed after use, with a signed receipt.

## Goals / non-goals / anti-goals

- **Goals**: production-style web app on a Vultr VM; agent plans via Vultr Serverless
  Inference; per-task sandboxed execution (Docker on the VM); live event stream of everything
  the agent does; visible containment (blast-radius panel + one-click torture tests); signed
  run receipts; one-command deploy to a fresh Vultr VM; works locally without any API key
  (mock mode) for development and CI.
- **Non-goals**: multi-tenant auth (single shared demo workspace), Pattern B browser-use lane
  at launch (architecture supports it; ship after Pattern A is solid), Kubernetes.
- **Anti-goals** (failure even if it "works"): secrets inside the sandbox; sandbox outliving
  its task; agent actions happening outside the event log; a demo that only works when the
  model behaves.

## Approaches considered

1. **Single-use-case agent (CSV Analyst only)** — smallest scope; many teams will build
   exactly this; weak Originality. Rejected as too narrow.
2. **Sandboxed browser-use agent (Site QA)** — high demo value, but heavy operational risk
   (Playwright-in-container, vision verification) and the containment story is harder to show.
   Deferred to a post-Pattern-A lane.
3. **Chosen: "Containment-as-a-product" workbench** — a platform that runs Pattern A lanes
   (CSV analyst / file fixer / chart anything) behind a visible containment layer, with
   built-in adversarial torture tests. Hits all four judging criteria: technology (Vultr VM +
   Serverless Inference + optional Vultr-API throwaway instances), presentation (mission-control
   UI makes containment visible), business value ("run untrusted agent work without risking your
   infrastructure"), originality (torture tests, policy engine, signed receipts).

## Architecture

```
Browser ──HTTP/SSE──► Control plane (FastAPI, Vultr VM)
                        │
                        ├─ Planner ──HTTPS──► Vultr Serverless Inference (OpenAI-compatible)
                        │      ▲                     (plan → code → fix → explain; no key
                        │      └─ real outputs       ever enters a sandbox)
                        │
                        ├─ Orchestrator ── per-task sandbox, lifecycle: create→run→destroy
                        │      │
                        │      ├─ DockerDriver   (prod: cap-drop ALL, read-only rootfs,
                        │      │                  mem/cpu/pids caps, wall-clock kill,
                        │      │                  egress-deny default, auto-remove)
                        │      ├─ LocalDriver    (dev on Windows: subprocess + tmpdir,
                        │      │                  same event contract; clearly labeled)
                        │      └─ VultrDriver    (stretch: throwaway Vultr instance per
                        │                         task via Vultr API, then destroyed)
                        │
                        ├─ Policy engine — every event risk-scored; violations kill the run
                        ├─ Receipts — hash-chained, downloadable proof of what ran
                        └─ SQLite (tasks, events, artifacts) + /workspace artifact store
```

**Flow (Pattern A):** user submits a goal + optional files → planner asks Vultr Inference for a
plan → planner writes Python to do the work → orchestrator runs it in a fresh sandbox →
stdout/stderr/artifacts/exit code stream back live → on error, the traceback goes back to the
model for a fix (max 3 revisions) → final model step explains the *real* output → sandbox
destroyed → receipt sealed.

**Containment invariants (the four from the brief):**
- *Process isolation*: agent code never executes in the control-plane process; the control
  plane's interpreter never sees user data paths from the sandbox.
- *Secret hygiene*: `VULTR_API_KEY` and all env stay in the control plane; sandboxes get a
  mounted workspace dir only — in Docker mode, not even the workspace path leaks env.
- *Resource limits*: wall-clock timeout, CPU count, memory, PID cap, output size cap per run.
- *Lifecycle discipline*: every sandbox is created per task and destroyed in a `finally`;
  destroy events are first-class UI events; a crashed run still destroys.

## The demo that wins

- **Lane 1 — Data analyst**: upload CSV, ask "which region grew fastest and chart it" → real
  executed pandas code, real PNG chart, real numbers in the explanation.
- **Lane 2 — File fixer**: upload a broken file, agent fixes it, diff shown.
- **Torture tests (one click each)**: `rm -rf /`, fork bomb, "print all env vars / curl the
  internet" exfiltration, a prompt-injection page. Each ends with: attempt blocked or absorbed,
  sandbox destroyed, host proof-of-life (pre/post hashes of host state), all on the timeline.
- **Receipt**: download the run receipt — hash chain of every event — "verifiable output."

## Build/run decisions (my calls)

- Python 3.14 + FastAPI + Jinja2 + vanilla JS + SSE (no Node toolchain — dev machine has none).
- SQLite via stdlib `sqlite3` (no ORM dependency).
- `httpx` for inference calls; `pydantic` for models; `pytest` for tests.
- Mock-LLM mode (`AIRLOCK_MOCK_LLM=1`) with canned-but-real plan/fix/explain behavior, so the
  full loop runs with zero keys; real key drops in via `AIRLOCK_INFERENCE_API_KEY`.
- Frontend: single dark "mission control" theme, three views (Launch pad, Task live view,
  Torture chamber), SSE for live updates, no build step.

## What's left to the builder (constraints, not prescriptions)

- Exact prompt wording for planner/fixer/explainer; JSON schema of the plan.
- Driver internals (Docker flags tuned on the actual VM; local driver mirrors the contract).
- UI copy and microcopy; visual identity details.
- VultrDriver specifics (instance plan/region, startup script) — feature-flagged, ships when
  the Vultr account + credits exist (kickoff day).

## Verification plan

- `pytest`: policy engine, orchestrator lifecycle (create→run→destroy even on crash), receipt
  chain integrity, API endpoints, local-driver end-to-end with mock LLM (CSV → chart artifact).
- Deploy smoke: `deploy/` scripts are idempotent and reviewed; full Docker path verified on the
  Vultr VM at kickoff (needs the real account).
