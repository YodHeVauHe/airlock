"""The planner: Airlock's reasoning loop over Vultr Serverless Inference.

plan → write code → (fix on failure) → explain from REAL outputs.

The planner never executes anything itself. It only produces text; every
side-effect goes through the sandbox, and the explainer is handed the run's
actual stdout/artifacts so the story the user reads is the story that happened.

System prompts intentionally contain the phrases the offline MockInference
keys on ("produce a JSON plan", "write a single python", "fix the code",
"explain the result") so mock and live modes follow the same contract.
"""
from __future__ import annotations

import json
import re
from typing import Any, Callable

from .llm import LLMResponse

Emit = Callable[..., Any]

PLAN_SYSTEM = """You are the planner for Airlock, a containment-first code-execution agent.
The user gives you a goal and a manifest of files already placed inside an isolated sandbox workspace.
Produce a JSON plan: {"approach": str, "steps": [str, ...]} with 3-5 concrete steps.
Rules: the agent can run ONE python script per step-attempt in the sandbox; the script may use the
standard library plus pandas/matplotlib if available; it reads inputs from the current directory and
writes any outputs (csv, charts) to the current directory; there is NO network access; do not plan
to read environment variables or secrets (there are none)."""

CODE_SYSTEM = """You are Airlock's engineer. Write a single python 3 script that accomplishes the user's
goal inside an isolated sandbox. Return JSON: {"code": "..."}.
Hard rules: no network access (no requests/urllib/socket), no environment variables, no subprocess,
no paths outside the current working directory; read inputs from cwd, write outputs to cwd;
print progress and a final line starting with RESULT: summarizing the outcome.
Prefer the standard library; pandas and matplotlib are available in the sandbox image if needed.
The script must be self-contained and deterministic."""

FIX_SYSTEM = """Fix the code. The previous attempt failed inside the sandbox.
Return JSON: {"code": "..."} with the full corrected script, same hard rules as before:
no network, no env vars, no subprocess, cwd-only file access, print a RESULT: line."""

EXPLAIN_SYSTEM = """You are Airlock's explainer. Explain the result to the user using ONLY the real
execution outputs provided (stdout, stderr, exit code, artifacts). Do not invent numbers.
Answer the user's goal directly, cite the actual figures from stdout, mention the artifacts by name.
Keep it under 180 words, markdown allowed."""


def _extract_json(text: str) -> dict:
    """Pull a JSON object out of an LLM response, tolerating fences and prose."""
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if fence:
        try:
            return json.loads(fence.group(1))
        except json.JSONDecodeError:
            pass
    brace = re.search(r"\{", text)
    if brace:
        depth = 0
        for i in range(brace.start(), len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[brace.start(): i + 1])
                    except json.JSONDecodeError:
                        break
    raise ValueError(f"no JSON object in model response: {text[:200]!r}")


def _extract_code(text: str) -> str:
    data = _extract_json(text)
    code = data.get("code", "")
    if not code.strip():
        raise ValueError("model returned empty code")
    return code


def _file_summary(files: dict[str, bytes], sample_bytes: int = 600) -> str:
    if not files:
        return "(no files uploaded — generate or synthesize any data the goal needs)"
    lines = []
    for name in sorted(files):
        blob = files[name]
        head = blob[:sample_bytes].decode("utf-8", errors="replace")
        lines.append(f"- {name} ({len(blob)} bytes). First bytes:\n---\n{head}\n---")
    return "\n".join(lines)


class Planner:
    def __init__(self, llm, emit: Emit, max_revisions: int = 3) -> None:
        self.llm = llm
        self.emit = emit
        self.max_revisions = max_revisions

    def _chat(self, system: str, user: str, *, json_mode: bool) -> LLMResponse:
        self.emit("llm.request", {"system": system.splitlines()[0][:80], "mode": "json" if json_mode else "text"})
        resp = self.llm.chat(system, user, json_mode=json_mode)
        self.emit("llm.response", {"model": resp.model, "chars": len(resp.text)})
        return resp

    def plan(self, goal: str, files: dict[str, bytes]) -> dict:
        resp = self._chat(PLAN_SYSTEM, f"GOAL: {goal}\n\nFILES IN SANDBOX WORKSPACE:\n{_file_summary(files)}", json_mode=True)
        data = _extract_json(resp.text)
        return {"approach": data.get("approach", ""), "steps": data.get("steps", []) or []}

    def write_code(self, goal: str, plan: dict, files: dict[str, bytes]) -> str:
        user = (
            f"Write a single python script per the rules to accomplish this goal.\n"
            f"GOAL: {goal}\nAPPROACH: {plan.get('approach','')}\n"
            f"STEPS: {json.dumps(plan.get('steps', []))}\n"
            f"FILES IN SANDBOX WORKSPACE:\n{_file_summary(files)}"
        )
        resp = self._chat(CODE_SYSTEM, user, json_mode=True)
        return _extract_code(resp.text)

    def fix_code(self, goal: str, code: str, stderr: str, exit_code: int, attempt: int) -> str:
        user = (
            f"GOAL: {goal}\nFix the code. The previous attempt failed (attempt {attempt}, exit {exit_code}).\n"
            f"PREVIOUS CODE:\n```python\n{code[-6000:]}\n```\n"
            f"TRACEBACK / STDERR:\n```\n{stderr[-3000:]}\n```\n"
            f"Return the full corrected script as JSON {{\"code\": ...}}."
        )
        resp = self._chat(FIX_SYSTEM, user, json_mode=True)
        return _extract_code(resp.text)

    def explain(self, goal: str, stdout: str, stderr: str, exit_code: int,
                artifact_names: list[str], killed_reason: str | None) -> str:
        real = (
            f"GOAL: {goal}\nEXIT CODE: {exit_code}"
            + (f" (sandbox killed: {killed_reason})" if killed_reason else "")
            + f"\nSTDOUT:\n{stdout[-3500:]}\nSTDERR:\n{stderr[-1500:]}\n"
            + ("ARTIFACTS:\n" + "\n".join(artifact_names) if artifact_names else "ARTIFACTS: none")
        )
        resp = self._chat(EXPLAIN_SYSTEM, real, json_mode=False)
        return resp.text.strip()
