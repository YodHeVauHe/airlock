# Security Policy

Airlock is a security product: its entire purpose is to guarantee that AI-generated code
executes without touching the host, the control plane, or any credentials. If you find a way to
break that guarantee, we want to hear from you — quickly and quietly.

## Reporting a vulnerability

**Do not open a public issue, discussion, or pull request for a security problem.** Public
details about a sandbox escape put every deployment at risk.

Use **GitHub's private vulnerability reporting** on this repository (Security tab →
"Report a vulnerability"), which notifies the maintainers privately. If you prefer email,
contact via the GitHub profile (@YodHeVauHe) and we will set up a private channel.

Please include:

- A description of the boundary you crossed (host filesystem, control-plane process, credential
  store, event-log integrity, receipt forgery…)
- Reproduction steps or a proof of concept — a torture test that *should* have contained your
  payload is the ideal form
- Which driver you used (`docker`, `local`, `vultr`) and the deployment context
- Your assessment of impact and any mitigation you'd suggest

## What counts as a security issue

- **Sandbox escape**: agent code reading or writing outside its workspace, executing in the
  control-plane process, or surviving its task's destruction.
- **Secret exposure**: any path by which `AIRLOCK_INFERENCE_API_KEY`, `VULTR_API_KEY`, control
  plane environment, or host credentials become visible to sandbox code.
- **Unauthorized egress**: sandbox code reaching the network when the driver's network policy
  denies it.
- **Resource-limit bypass**: CPU/memory/PID/time caps that can be exceeded beyond a reasonable
  grace margin.
- **Log or receipt integrity**: modifying, reordering, removing, or forging events without the
  hash chain breaking, or a receipt passing `verify_receipt` after tampering.

A crash *inside* the sandbox, or sandbox code destroying its own workspace, is working as
designed — that's what the Torture Chamber is for. Please do report it if the *host
fingerprint* changes, though; that is exactly the breach signal the product promises to catch.

## Response

- Acknowledgment within **72 hours**.
- Triage and severity assessment within **7 days**.
- Fix or mitigation target: **30 days** for high severity, next release otherwise.
- You'll be kept informed throughout, credited in the changelog if you wish, and — once a fix
  ships — are welcome to publish your findings.

## Safe harbor

We consider security research conducted in good faith — respecting the privacy of other users,
using your own deployments, and reporting privately through this policy — to be authorized, and
we will not pursue legal action over it.

## Deployment hardening notes

If you operate an Airlock deployment:

- Run it on a dedicated VM (as in `deploy/`), never on a machine that holds other duties.
- Keep the Docker socket mount **read-only** and never expose it over the network.
- Only ports 22 and 80/443 need to be reachable; sandboxes get no network regardless.
- Keep `AIRLOCK_POLICY_MODE=enforce` outside of controlled experiments.
- Treat the `vultr` throwaway-instance driver as experimental until it has had an audit.
