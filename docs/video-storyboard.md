# Demo video — storyboard (target: 3 minutes)

The hackathon requires ONE containment moment on camera. This script has two: the rm-rf
detonation (hero moment) and the sandbox destruction lifecycle. Record at 1920×1080,
browser zoom 110–125%, dark IDE theme, narration pace calm.

## Shot list

### 0:00–0:20 — Hook (talking head or slides)
"Everyone wants AI agents that do real work. Nobody lets them near real infrastructure —
because the blast radius of one bad generation is YOUR machine. This is Airlock:
real executed work, zero blast radius, running on Vultr."

### 0:20–0:45 — The problem, visualized (slide: architecture diagram)
- Left: "typical agent" — code executes next to your app, with your env vars, your network.
- Right: Airlock — plan (Vultr Serverless Inference) → sandbox → verify → destroy.
- Read the four invariants aloud: process isolation, secret hygiene, resource limits,
  lifecycle discipline.

### 0:45–1:45 — Real work, live (screen: Launch pad)
1. Upload `samples/sales.csv`.
2. Type: "Which region has the highest average revenue? Chart it."
3. Dispatch. Narrate the timeline AS IT STREAMS: plan arrives → generated code appears →
   policy verdict → sandbox created (point at the limits line: no network, mem cap, PID cap)
   → executed → artifacts appear → explanation from real output.
4. Open the chart artifact. "east, 28,546 — computed, not hallucinated."
5. Download the receipt. Open it in the editor; point at the hash chain head.

### 1:45–2:30 — THE CONTAINMENT MOMENT (screen: Torture Chamber)
1. "Don't take containment on faith. Watch."
2. Click **⚡ Detonate** on `rm -rf /`.
3. Let the timeline play: policy findings tagged risk:3 → sandbox created → the delete
   bounces off the read-only rootfs → **sandbox destroyed** → host fingerprint
   before == after → banner: CONTAINED.
4. "It just tried to erase the entire filesystem. The host fingerprint never changed.
   The sandbox is gone. That is blast-radius zero."
5. (If time) Quick second detonation: env-probe — "nothing to steal."

### 2:30–3:00 — Business value + close (slide)
- "Airlock is the trust layer between LLM agents and production: data teams, ops, support
  automation — anywhere an agent should touch real work but you can't afford a bad day."
- Stack recap, 3 bullets: Vultr VM + Docker containment, Vultr Serverless Inference for all
  reasoning, throwaway Vultr instances per task (show the Vultr console instance created →
  destroyed clip if the stretch lane is enabled).
- Close on the receipt: "Every run ends with a verifiable receipt. That's the product."

## Recording notes
- Use the deployed Vultr URL (public demo) for all screen recording — judges must see it
  running on Vultr.
- Keep the blast-radius panel visible in every task shot.
- If the throwaway-instance lane is enabled: record the Vultr console instance list in a
  second window while a task boots and destroys its VM. Strong differentiator footage.
- Upload: YouTube (public or unlisted) + lablab submission form.
