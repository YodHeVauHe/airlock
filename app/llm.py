"""Vultr Serverless Inference client (OpenAI-compatible) + offline mock.

All agent reasoning in Airlock goes through Vultr Serverless Inference
(https://api.vultrinference.com/v1) — per the challenge rules. When no API key
is configured (or AIRLOCK_MOCK_LLM=1), a deterministic mock takes over so the
whole product runs locally and in CI with zero credentials. The mock still
produces REAL executed results — it plans and writes genuine Python that runs
in the sandbox; it just doesn't phone a model.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

import httpx

from .config import Settings


@dataclass
class LLMResponse:
    text: str
    model: str
    usage: dict[str, Any]


class InferenceError(RuntimeError):
    pass


class VultrInference:
    """Thin OpenAI-compatible chat client for Vultr Serverless Inference."""

    def __init__(self, settings: Settings) -> None:
        self.base_url = settings.inference_base_url
        self.api_key = settings.inference_api_key
        self.model = settings.inference_model
        self._client = httpx.Client(
            base_url=self.base_url,
            headers={"Authorization": f"Bearer {self.api_key}"} if self.api_key else {},
            timeout=90.0,
        )

    def list_models(self) -> list[str]:
        r = self._client.get("/models")
        r.raise_for_status()
        data = r.json().get("data", [])
        return [m.get("id", "?") for m in data]

    def chat(self, system: str, user: str, *, json_mode: bool = False, max_tokens: int = 2048) -> LLMResponse:
        model = self.model
        if not model:
            models = self.list_models()
            if not models:
                raise InferenceError("No models available on Vultr Serverless Inference")
            model = models[0]
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        body: dict[str, Any] = {"model": model, "messages": messages, "max_tokens": max_tokens}
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        r = self._client.post("/chat/completions", json=body)
        if r.status_code >= 400:
            raise InferenceError(f"inference HTTP {r.status_code}: {r.text[:400]}")
        data = r.json()
        choice = data["choices"][0]
        text = choice["message"]["content"]
        return LLMResponse(text=text, model=data.get("model", model), usage=data.get("usage", {}))


class MockInference:
    """Deterministic offline stand-in with the same surface as VultrInference.

    It never fabricates results: it writes code the sandbox really executes,
    and the explainer works from the run's actual stdout/artifacts.
    """

    model = "mock-analyst"

    def list_models(self) -> list[str]:
        return [self.model]

    def chat(self, system: str, user: str, *, json_mode: bool = False, max_tokens: int = 2048) -> LLMResponse:
        kind = _detect_intent(system, user)
        if kind == "plan":
            text = json.dumps({
                "approach": "Inspect the data with pandas-style summaries, compute per-group aggregates, "
                            "write summary.csv and render a bar chart.",
                "steps": [
                    "Load the input file and report its shape and columns",
                    "Compute per-category aggregates and save summary.csv",
                    "Render a bar chart of the largest category to chart.png",
                    "Print the headline numbers for the explainer",
                ],
            })
        elif kind == "code":
            text = json.dumps({"code": MOCK_ANALYST_CODE})
        elif kind == "explain":
            # The user payload carries the REAL stdout + artifact list.
            text = _mock_explain(user)
        else:  # fix
            text = json.dumps({"code": MOCK_ANALYST_CODE})
        return LLMResponse(text=text, model=self.model, usage={"mock": True})


def _detect_intent(system: str, user: str) -> str:
    s = (system + " " + user[:400]).lower()
    if "produce a json plan" in s or '"approach"' in s and "plan" in s:
        return "plan"
    if "explainer" in s or "explain the result" in s:
        return "explain"
    if "fix the code" in s or "previous attempt failed" in s or "traceback" in user.lower():
        return "fix"
    if "write a single python" in s or "return json with a single key" in s:
        return "code"
    return "plan"


MOCK_ANALYST_CODE = '''\
"""Mock-analyst workload: real code that really runs inside the sandbox.

Uses only the standard library so it runs anywhere (the Docker sandbox image
also ships pandas/matplotlib; the live model will use them when present).
"""
import csv
import os
from collections import defaultdict

WORKDIR = os.getcwd()

def _find_input():
    for name in sorted(os.listdir(WORKDIR)):
        if name.lower().endswith((".csv", ".tsv")) and not name.startswith("summary"):
            return name
    return None

def _render_svg_bars(path, labels, values, title):
    width, bar_h, pad, top = 720, 36, 8, 60
    height = top + len(labels) * (bar_h + pad) + 40
    vmax = max(values) if values else 1
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">',
             '<rect width="100%" height="100%" fill="#0d1117"/>',
             f'<text x="20" y="34" fill="#e6edf3" font-family="monospace" font-size="20">{title}</text>']
    for i, (lab, val) in enumerate(zip(labels, values)):
        y = top + i * (bar_h + pad)
        w = int((width - 240) * (val / vmax))
        parts.append(f'<rect x="180" y="{y}" width="{max(w,2)}" height="{bar_h}" rx="4" fill="#58a6ff"/>')
        parts.append(f'<text x="170" y="{y+25}" fill="#8b949e" font-family="monospace" font-size="14" text-anchor="end">{str(lab)[:24]}</text>')
        parts.append(f'<text x="{182+max(w,2)}" y="{y+25}" fill="#e6edf3" font-family="monospace" font-size="14">{val:.2f}</text>')
    parts.append("</svg>")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\\n".join(parts))

def _mean(xs):
    return sum(xs) / len(xs) if xs else 0.0

def main():
    name = _find_input()
    if not name:
        print("NO_INPUT: no csv/tsv file found in workspace")
        return 1
    sep = "\\t" if name.endswith(".tsv") else ","
    numeric = defaultdict(list)
    with open(os.path.join(WORKDIR, name), newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh, delimiter=sep):
            for k, v in row.items():
                if k is None or v is None:
                    continue
                try:
                    numeric[k].append(float(v))
                except ValueError:
                    pass
    summary_rows = []
    for col, vals in sorted(numeric.items()):
        if not vals:
            continue
        summary_rows.append((col, len(vals), _mean(vals), min(vals), max(vals)))
    with open(os.path.join(WORKDIR, name), newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh, delimiter=sep)
        first = reader.fieldnames[0] if reader.fieldnames else None
    groups = defaultdict(list)
    numeric_cols = [c for c, *_ in summary_rows]
    if first and first not in numeric_cols:
        with open(os.path.join(WORKDIR, name), newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh, delimiter=sep):
                key = row.get(first)
                vals = []
                for c in numeric_cols:
                    try:
                        vals.append(float(row.get(c, "")))
                    except (ValueError, TypeError):
                        pass
                if key is not None and vals:
                    groups[key].append(_mean(vals))
    with open(os.path.join(WORKDIR, "summary.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["column", "count", "mean", "min", "max"])
        for col, n, mean, mn, mx in summary_rows:
            w.writerow([col, n, f"{mean:.4f}", f"{mn:.4f}", f"{mx:.4f}"])
        if groups:
            w.writerow([])
            w.writerow([f"group_by:{first}", "n", "mean_of_numeric_cols", "", ""])
            for g in sorted(groups, key=lambda g: -_mean(groups[g])):
                w.writerow([g, len(groups[g]), f"{_mean(groups[g]):.4f}", "", ""])
    labels = sorted(groups, key=lambda g: -_mean(groups[g]))[:8]
    values = [_mean(groups[g]) for g in labels]
    _render_svg_bars(os.path.join(WORKDIR, "chart.svg"), labels, values, f"Mean of numeric columns by {first}")
    print(f"OK rows_grouped={len(groups)} columns_summarized={len(summary_rows)}")
    print("TOP_GROUP=" + (labels[0] if labels else "n/a"))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
'''


def _mock_explain(user: str) -> str:
    """Build the explainer's markdown from the run's REAL outputs."""
    m = re.search(r"STDOUT:\n(.*?)(?:\nARTIFACTS:|$)", user, re.S)
    stdout = (m.group(1) if m else "").strip()
    m2 = re.search(r"ARTIFACTS:\n(.*?)$", user, re.S)
    artifacts = (m2.group(1) if m2 else "").strip()
    lines = ["## What actually happened", ""]
    lines.append("The sandbox executed the generated script; everything below comes from its real output.")
    lines.append("")
    if stdout:
        lines.append("**Sandbox output**")
        lines.append("```")
        for line in stdout.splitlines()[:10]:
            lines.append(line)
        lines.append("```")
    if artifacts:
        lines.append("**Artifacts written by the sandbox**")
        for a in artifacts.splitlines():
            lines.append(f"- `{a.strip()}`")
    lines.append("")
    lines.append("_Mock mode: set `AIRLOCK_INFERENCE_API_KEY` to route this step through Vultr Serverless Inference._")
    return "\n".join(lines)


def make_llm(settings: Settings):
    if settings.llm_is_mock:
        return MockInference()
    return VultrInference(settings)
