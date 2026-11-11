from __future__ import annotations

import json

from codehealth.cli import main

from .conftest import FIXTURES


def test_review_text(capsys):
    assert main(["review", str(FIXTURES / "go" / "smelly.go")]) == 0
    out = capsys.readouterr().out
    assert "(Warning)" in out and "Bumpy Road Ahead Bumpy" in out


def test_score_json_directory(capsys):
    assert main(["score", "--json", str(FIXTURES / "java")]) == 0
    data = json.loads(capsys.readouterr().out)
    assert {d["score"] for d in data if d["path"].endswith("Clean.java")} == {10.0}


def test_unsupported_file_errors(tmp_path, capsys):
    target = tmp_path / "a.txt"
    target.write_text("x")
    assert main(["review", str(target)]) == 2
    assert "unsupported" in capsys.readouterr().err


def _complex_module() -> str:
    body = "    if a:\n        return 1\n    if b:\n        return 2\n    if c:\n        return 3\n    return 4\n"
    return "".join(f"def f{i}(a, b, c):\n{body}" for i in range(3))


def test_file_level_findings_have_null_lines(tmp_path, capsys):
    target = tmp_path / "m.py"
    target.write_text(_complex_module())
    assert main(["review", "--json", str(target)]) == 0
    findings = json.loads(capsys.readouterr().out)[0]["findings"]
    overall = [f for f in findings if f["smell"] == "Overall Code Complexity"]
    assert overall and overall[0]["start_line"] is None and overall[0]["end_line"] is None
    assert main(["review", str(target)]) == 0
    line = next(x for x in capsys.readouterr().out.splitlines() if "Overall Code Complexity" in x)
    assert "[lines" not in line
