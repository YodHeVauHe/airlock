# Lablab submission copy (paste into the form on Nov 3–8)

## Project title
Airlock — Blast-Radius-Zero Agent Execution on Vultr

## Short description (≤ 200 chars)
Give your AI agent real work — analysis, charts, file fixes — executed in disposable sandboxes
on Vultr: no network, no secrets, hard caps, destroyed after every task. Signed, verifiable
receipts included.

## Long description

Nobody lets AI agents touch real infrastructure, because one hallucinated `rm -rf /` — or one
prompt injection — lands on YOUR machine. Airlock makes containment the product.

Airlock is a production-style web app on a Vultr VM. You hand it real work: analyze this CSV,
which region leads, chart it. A planner built on Vultr Serverless Inference turns the goal into
a plan, writes Python, and every attempt executes inside a fresh sandbox: Docker with
--network none, --cap-drop ALL, read-only rootfs, memory/CPU/PID ceilings, a wall-clock kill,
and an unprivileged user — created per task and ALWAYS destroyed afterwards, even on crash.
An experimental driver goes further: an entire throwaway Vultr instance per task, via the
Vultr API, destroyed the moment the run ends.

Everything is visible. The mission-control UI streams a live, hash-chained timeline: the plan,
each generated code version, the policy verdict, the sandbox lifecycle, real stdout, real
artifacts. A blast-radius panel shows secrets exposed (none — the sandbox env has nothing to
steal), network egress (none — no route out), and the host fingerprint hash before/after.

The Torture Chamber proves it: one-click detonations of rm -rf /, a fork bomb, environment
exfiltration, and internet call-homes — each absorbed on camera, ending with CONTAINED and an
unchanged host fingerprint. That's the demo's containment moment, built into the product.

Every run ends with a downloadable receipt: a SHA-256 hash chain of every event, verifiable by
anyone. Real executed results. Zero blast radius. Signed proof.

## Tags
vultr, sandboxing, docker, agents, code-execution, ai-safety, fastapi, serverless-inference,
containment, receipts

## Cover image
To produce: dark mission-control screenshot — task timeline with risk tags + blast-radius
panel + CONTAINED banner. (Ask ZCode to render/screenshot, or capture from the live app.)

## Links
- GitHub repo: (push airlock/ here)
- Demo URL: http://<vultr-vm-ip>/ (or domain)
- Video: (per docs/video-storyboard.md)
