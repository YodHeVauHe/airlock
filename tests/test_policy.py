import json

from app.policy import scan_code, is_hard_blocked, score_explanation


def test_clean_code_has_no_findings():
    code = (
        "import csv\n"
        "with open('data.csv') as fh:\n"
        "    rows = list(csv.reader(fh))\n"
        "print(len(rows))\n"
    )
    assert scan_code(code) == []
    assert score_explanation(scan_code(code)).startswith("Clean")


def test_secret_probe_detected():
    findings = scan_code("import os\nprint(os.environ['API_KEY'])\n")
    tags = {f.tag for f in findings}
    assert "secret-probe" in tags


def test_egress_attempt_detected():
    findings = scan_code("import requests\nrequests.get('https://evil.example')\n")
    tags = {f.tag for f in findings}
    assert "egress-attempt" in tags
    assert max([f.severity for f in findings]) == 3


def test_socket_import_caught_via_ast():
    findings = scan_code("import socket\ns = socket.socket()\n")
    assert any(f.tag == "egress-attempt" for f in findings)


def test_destructive_fs_detected():
    findings = scan_code("import shutil\nshutil.rmtree('/', ignore_errors=True)\n")
    assert any(f.tag == "destructive-fs" for f in findings)


def test_ctypes_escape_attempt():
    findings = scan_code("import ctypes\n")
    assert any(f.tag == "escape-attempt" for f in findings)


def test_enforce_mode_blocks_hostile_code():
    code = "import os\nprint(os.environ)\n"
    findings = scan_code(code)
    assert is_hard_blocked(findings, "enforce", torture=False)
    # monitor mode records but allows
    assert not is_hard_blocked(findings, "monitor", torture=False)
    # torture runs bypass the gate by design (containment layer's audition)
    assert not is_hard_blocked(findings, "enforce", torture=True)


def test_benign_process_spawn_is_medium_not_blocked():
    findings = scan_code("import subprocess\nprint(subprocess.run(['ls']))\n")
    assert max([f.severity for f in findings]) == 2
    assert not is_hard_blocked(findings, "enforce", torture=False)
