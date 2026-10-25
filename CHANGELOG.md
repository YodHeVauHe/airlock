# Changelog

All notable changes to Airlock are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning is
[SemVer](https://semver.org/).

## [0.1.0] — 2026-10-25

First public release, built for the Vultr: Agent Rush Hackathon (Challenge 1 —
Blast Radius Zero).

### Added

- Control plane (FastAPI): task launch, live SSE event stream, task history,
  artifact serving, receipt download and verification endpoints.
- Agent loop over Vultr Serverless Inference (OpenAI-compatible): plan →
  generated code → traceback-fed revision (bounded) → explanation composed from
  real execution output. Deterministic offline mock with the same contract.
- Sandbox drivers, one per task, always destroyed afterwards:
  - `docker` — production containment (`--network none`, `--cap-drop ALL`,
    `no-new-privileges`, read-only rootfs, memory/CPU/PID ceilings, wall-clock
    kill, unprivileged user, scratch-built environment with no secrets).
  - `local` — subprocess driver for development machines (clearly labeled;
    not a containment boundary).
  - `vultr` — experimental: a throwaway Vultr instance per task via the Vultr
    API, HMAC-signed result callback, destroyed by the control plane in a
    `finally` block.
- Policy engine: pre-execution AST + pattern scan of generated code, risk
  scoring, enforce mode that refuses hostile code before any sandbox exists.
- Hash-chained event log with live fan-out; sealed, downloadable run receipts
  with independent verification.
- Torture Chamber: one-click `rm -rf /`, fork bomb, environment exfiltration,
  and egress probes, each receipted, each ending with a host-fingerprint
  before/after proof.
- Mission-control web UI (buildless): launch pad, live timeline with
  blast-radius panel, torture chamber.
- Deployment: docker-compose production stack, one-shot VM setup script,
  cloud-init user data for Vultr, DEPLOY.md walkthrough.
- Test suite: 18 tests covering policy, agent lifecycle (including timeout
  kills and guaranteed sandbox destruction), receipt tamper-evidence, the API
  surface, and torture-run containment.
