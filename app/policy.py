"""The policy engine: static analysis of agent-generated code + blast-radius scoring.

Two layers of defense:
  1. Pre-execution scan — every snippet the model writes is inspected before it
     ever touches a sandbox. Findings are recorded as policy events with a risk
     score. In ``enforce`` mode, HARD blocks refuse to run.
  2. Containment assumptions — the sandbox itself (driver) enforces what static
     analysis cannot: no network, no secrets, resource caps, destruction after
     use. Torture tests exist to demonstrate that layer.

Severity levels map to the blast-radius panel:
  0 info · 1 low · 2 medium · 3 high
"""
from __future__ import annotations

import ast
import dataclasses
import re

# (tag, severity, regex, message) — quick textual tripwires
TEXT_RULES = [
    ("secret-probe", 3, re.compile(r"os\.environ|os\.getenv|environ\[|passw|api[_-]?key|token", re.I),
     "Code reads environment variables or looks for credentials."),
    ("egress-attempt", 3, re.compile(r"\b(requests|urllib|httpx|socket|http\.client)\b"),
     "Code attempts network access. Sandboxes have no network."),
    ("process-spawn", 2, re.compile(r"\b(subprocess|os\.system|os\.popen|os\.exec|os\.spawn)\b"),
     "Code spawns external processes."),
    ("destructive-fs", 3, re.compile(r"rmtree|unlink\(|remove\(|\brm\s+-rf\b|shutil\.rmtree"),
     "Code deletes files or directories."),
    ("host-paths", 2, re.compile(r"""open\(\s*['"]/(etc|root|home|proc|sys|var)""", re.I),
     "Code opens host system paths outside its workspace."),
    ("eval-use", 2, re.compile(r"\beval\s*\(|\bexec\s*\("),
     "Code uses eval/exec — dynamic execution."),
    ("busy-loop", 1, re.compile(r"while\s+True\s*:"),
     "Unbounded loop detected; CPU and wall-clock caps apply."),
]

# AST rules for things regex shouldn't guess at
IMPORT_BLOCKLIST = {
    "socket": ("egress-attempt", 3, "Imports socket — raw network access."),
    "requests": ("egress-attempt", 3, "Imports requests — network access."),
    "httpx": ("egress-attempt", 3, "Imports httpx — network access."),
    "urllib": ("egress-attempt", 3, "Imports urllib — network access."),
    "subprocess": ("process-spawn", 2, "Imports subprocess — can spawn processes."),
    "ctypes": ("escape-attempt", 3, "Imports ctypes — native-code escape attempts."),
    "multiprocessing": ("resource-abuse", 2, "Imports multiprocessing — process fan-out."),
}


@dataclasses.dataclass
class Finding:
    tag: str
    severity: int
    message: str
    where: str = ""

    def as_dict(self) -> dict:
        return {"tag": self.tag, "severity": self.severity, "message": self.message, "where": self.where}


# Tags that refuse to run in enforce mode (torture-test runs bypass this gate
# deliberately — that is the point of a torture test: prove containment).
HARD_BLOCK_TAGS = {"secret-probe", "egress-attempt", "destructive-fs", "escape-attempt"}


def scan_code(code: str) -> list[Finding]:
    findings: list[Finding] = []
    for tag, sev, rx, msg in TEXT_RULES:
        m = rx.search(code)
        if m:
            line = code[: m.start()].count("\n") + 1
            findings.append(Finding(tag, sev, msg, f"line {line}"))
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return findings
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root in IMPORT_BLOCKLIST:
                    tag, sev, msg = IMPORT_BLOCKLIST[root]
                    findings.append(Finding(tag, sev, msg, f"line {node.lineno}"))
        elif isinstance(node, ast.ImportFrom) and node.module:
            root = node.module.split(".")[0]
            if root in IMPORT_BLOCKLIST:
                tag, sev, msg = IMPORT_BLOCKLIST[root]
                findings.append(Finding(tag, sev, msg, f"line {node.lineno}"))
    # dedupe by (tag, where)
    seen = set()
    unique = []
    for f in findings:
        key = (f.tag, f.where)
        if key not in seen:
            seen.add(key)
            unique.append(f)
    return unique


def max_severity(findings: list[Finding]) -> int:
    return max((f.severity for f in findings), default=0)


def is_hard_blocked(findings: list[Finding], mode: str, torture: bool) -> bool:
    if torture or mode != "enforce":
        return False
    return any(f.tag in HARD_BLOCK_TAGS for f in findings)


def score_explanation(findings: list[Finding]) -> str:
    """One-line blast-radius verdict for the UI."""
    if not findings:
        return "Clean: no secrets touched, no network, workspace-only writes."
    top = max_severity(findings)
    if top >= 3:
        return "Hostile pattern detected — contained by the sandbox, never reached the host."
    if top == 2:
        return "Risky pattern detected — monitored and capped by the sandbox."
    return "Minor pattern detected — within policy."
