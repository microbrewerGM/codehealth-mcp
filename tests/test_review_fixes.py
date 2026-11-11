"""Regression tests for the independent review batch (S1-S3, C1-C8)."""

from __future__ import annotations

import asyncio
import json
import subprocess
import time
from pathlib import Path

import pytest
from mcp import Client

from codehealth import config, delta
from codehealth.analysis import FileTooLargeError, review_file, review_source
from codehealth.config import Rules
from codehealth.lang import parse_source
from codehealth.server import server
from codehealth.thresholds import defaults_for

from .conftest import FIXTURES, git

FIVE_ARGS = "def f(a, b, c, d, e):\n    return a\n"
CLEAN = "def f(a):\n    return a\n"


def commit(repo: Path, files: dict[str, str], message: str = "c") -> None:
    for rel, text in files.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(text)
        git(repo, "add", rel)
    git(repo, "commit", "-q", "-m", message)


# ----- S1: no worktree-reading git commands (clean filters never run) ------------
def test_clean_filter_never_runs(repo, tmp_path_factory):
    marker = tmp_path_factory.mktemp("m") / "filter-ran"
    commit(repo, {"a.py": CLEAN})
    git(repo, "checkout", "-q", "-b", "feature")
    commit(repo, {"a.py": FIVE_ARGS})
    git(repo, "config", "filter.x.clean", f"sh -c 'touch {marker}; cat'")
    (repo / ".gitattributes").write_text("*.py filter=x\n")
    (repo / "a.py").write_text(FIVE_ARGS + "\n# edited\n")
    delta.pre_commit_safeguard(repo)
    delta.analyze_change_set(repo, "main")
    delta.file_delta_against_ref(repo, "a.py")
    assert not marker.exists()
    # Sanity check: a worktree diff through git does run the filter.
    subprocess.run(["git", "-C", str(repo), "diff", "HEAD"], capture_output=True, check=False)
    assert marker.exists()


# ----- S2: validate refuses symlinks and does not echo content -------------------
def _call(name: str, args: dict):
    async def go():
        async with Client(server) as client:
            return await client.call_tool(name, args)

    return asyncio.run(go())


def test_validate_refuses_symlinked_rules_file(repo, tmp_path_factory):
    outside = tmp_path_factory.mktemp("o") / "secret.json"
    outside.write_text('{"rule_sets": [{"rules": [{"name": "TOP-SECRET", "weight": 1}]}]}')
    (repo / ".codehealth").mkdir()
    (repo / ".codehealth" / "rules.json").symlink_to(outside)
    result = _call("rules_config_validate", {"repository_path": str(repo)})
    assert result.is_error
    assert "TOP-SECRET" not in result.content[0].text


def test_validate_truncates_untrusted_names(repo):
    long_name = "X" * 500
    config_dir = repo / ".codehealth"
    config_dir.mkdir()
    (config_dir / "rules.json").write_text(json.dumps({"rule_sets": [{"rules": [{"name": long_name, "weight": 1}]}]}))
    data = _call("rules_config_validate", {"repository_path": str(repo)}).structured_content
    assert data["valid"] is False
    assert "X" * 81 not in data["errors"][0] and "X" * 80 in data["errors"][0]


# ----- S3: config search scope ------------------------------------------------------
def _disable_args_rules(directory: Path) -> None:
    path = directory / ".codehealth" / "rules.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"rule_sets": [{"rules": [{"name": "Excess Number of Function Arguments", "weight": 0}]}]}))


def test_config_outside_repo_only_same_directory(tmp_path):
    _disable_args_rules(tmp_path)
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "f.py").write_text(FIVE_ARGS)
    (tmp_path / "f.py").write_text(FIVE_ARGS)
    assert review_file(tmp_path / "sub" / "f.py").findings  # parent rules ignored
    assert not review_file(tmp_path / "f.py").findings  # same directory applies


def test_config_never_above_repo_root(tmp_path):
    _disable_args_rules(tmp_path)
    inner = tmp_path / "repo"
    inner.mkdir()
    git(inner, "init", "-q")
    (inner / "f.py").write_text(FIVE_ARGS)
    assert config.find_config(inner / "f.py") is None
    assert review_file(inner / "f.py").findings


# ----- C1: non-ASCII paths ------------------------------------------------------------
def test_non_ascii_paths(repo):
    commit(repo, {"naïve/ünïcode.py": CLEAN})
    git(repo, "checkout", "-q", "-b", "feature")
    commit(repo, {"naïve/ünïcode.py": FIVE_ARGS})
    result = delta.analyze_change_set(repo, "main")
    assert [f["path"] for f in result["files"]] == ["naïve/ünïcode.py"]
    (repo / "naïve/ünïcode.py").write_text(CLEAN)
    assert [f["path"] for f in delta.pre_commit_safeguard(repo)["files"]] == ["naïve/ünïcode.py"]


# ----- C2: renames ------------------------------------------------------------------------
def test_rename_with_unchanged_content_is_stable(repo):
    commit(repo, {"a.py": FIVE_ARGS})
    git(repo, "checkout", "-q", "-b", "feature")
    git(repo, "mv", "a.py", "b.py")
    staged = delta.pre_commit_safeguard(repo)
    assert [(f["path"], f["verdict"]) for f in staged["files"]] == [("b.py", "stable")]
    assert staged["quality_gate"] == "passed"
    git(repo, "commit", "-q", "-m", "rename")
    result = delta.analyze_change_set(repo, "main")
    assert [(f["path"], f["verdict"]) for f in result["files"]] == [("b.py", "stable")]
    assert result["quality_gate"] == "passed"


# ----- C3: identity -------------------------------------------------------------------------
OVERLOADS = """class A {
  void f(int a, int b, int c, int d, int e) {}
  void f(int a, int b, int c, int d, int e, int g) {}
}
"""


def test_overloads_get_ordinal_identities():
    parsed = parse_source(OVERLOADS, "A.java")
    assert [f.identity for f in parsed.functions] == ["A.f", "A.f#1"]


def test_identity_survives_line_shifts():
    shifted = OVERLOADS.replace("class A {\n", "class A {\n  void clean() {}\n\n\n")
    result = delta.compare_sources(Path("A.java"), OVERLOADS, shifted)
    assert result.verdict == "stable", result.to_dict()
    worse = OVERLOADS.replace("int g)", "int g, int h)")
    result = delta.compare_sources(Path("A.java"), OVERLOADS, worse)
    assert [w["function"] for w in result.worsened] == ["A.f"] and result.verdict == "degraded"
    assert [f.identity for f in review_source(worse, Path("A.java")).findings] == ["A.f", "A.f#1"]


def test_anonymous_identity_has_no_line_number():
    src = "const xs = [class { m() { return this.a; } }, class { m() { return this.b; } }];\n"
    parsed = parse_source(src, "x.js")
    assert [c.identity for c in parsed.classes] == ["<anonymous>", "<anonymous>#1"]
    shifted = parse_source("\n\n// moved\n" + src, "x.js")
    assert [c.identity for c in shifted.classes] == ["<anonymous>", "<anonymous>#1"]
    assert [f.identity for f in shifted.functions] == ["<anonymous>.m", "<anonymous>#1.m"]


# ----- C4: gate semantics and removed files ------------------------------------------------
def test_removed_file_does_not_block_gate(repo):
    commit(repo, {"a.py": FIVE_ARGS, "b.py": CLEAN})
    (repo / "a.py").unlink()
    result = delta.pre_commit_safeguard(repo)
    [entry] = result["files"]
    assert entry["verdict"] == "removed" and entry["old_score"] < 10
    assert result["quality_gate"] == "passed"
    assert result["counts"] == {"removed": 1}


def test_unknown_verdict_fails_gate():
    unknown = delta.compare_sources(Path("a.txt"), "x", "y")
    assert unknown.verdict == "unknown" and not unknown.gate_passed
    assert delta.summarize([unknown])["quality_gate"] == "failed"


# ----- C5: rules come from the base revision ------------------------------------------------
def test_base_rules_apply_and_changes_are_flagged(repo):
    commit(repo, {"a.py": CLEAN})
    git(repo, "checkout", "-q", "-b", "feature")
    rules = {"rule_sets": [{"rules": [{"name": "Excess Number of Function Arguments", "weight": 0}]}]}
    commit(repo, {".codehealth/rules.json": json.dumps(rules), "a.py": FIVE_ARGS})
    result = delta.analyze_change_set(repo, "main")
    assert result["files"][0]["verdict"] == "degraded"
    assert result["rules_changed"] is True
    assert result["rules_diff"] == [
        {"matching_content_path": "**/*", "kind": "rules", "name": "Excess Number of Function Arguments", "old": None, "new": 0}
    ]


def test_precommit_flags_worktree_rules_change(repo):
    commit(repo, {"a.py": CLEAN})
    config.set_rule(repo, "Large Method", 0)
    (repo / "a.py").write_text(FIVE_ARGS)
    result = delta.pre_commit_safeguard(repo)
    assert result["rules_changed"] is True and result["quality_gate"] == "failed"


# ----- C6: anonymous class bodies are not methods of the enclosing class -------------------
def test_java_anonymous_class_methods_not_attributed():
    src = """class Outer {
  int x;
  Runnable r = new Runnable() { public void run() { x++; } };
  void a() { x++; }
}
"""
    [outer] = [c for c in parse_source(src, "O.java").classes if c.name == "Outer"]
    assert [m.name for m in outer.methods] == ["a"]


def test_js_object_literal_and_class_expression_methods_not_attributed():
    src = """class Outer {
  handlers = { a() { return 1; } };
  m() { const Inner = class { z() { return 2; } }; return Inner; }
  n() { return this.handlers; }
}
"""
    classes = {c.name: c for c in parse_source(src, "x.js").classes}
    assert [m.name for m in classes["Outer"].methods] == ["m", "n"]
    assert [m.name for m in classes["<anonymous>"].methods] == ["z"]


# ----- C7: Complex Conditional value is the worst operator count --------------------------
def test_complex_conditional_value_is_worst_operator_count():
    review = review_file(FIXTURES / "tsx" / "smelly.tsx")
    cond = next(f for f in review.findings if f.smell == "Complex Conditional")
    assert (cond.value, cond.threshold, cond.details["count"]) == (3, 2, 1)


# ----- C8: performance and size guard -----------------------------------------------------
def _timed_review(n: int):
    src = "".join(f"def f{i}(a):\n    return a + {i}\n" for i in range(n))
    start = time.perf_counter()
    review = review_source(src, Path("big.py"))
    return time.perf_counter() - start, review


def test_review_scales_linearly_to_twenty_thousand_functions():
    """Guards against quadratic cliffs (the old lines_between scan) without a wall-clock limit
    that flakes on a loaded machine: 10x the functions must cost well under 100x the time."""
    small, _ = _timed_review(2_000)
    large, review = _timed_review(20_000)
    assert review.function_count == 20_000
    assert large < 25 * max(small, 0.05)
    assert large < 30.0  # sanity ceiling, far above the ~6 s observed


def test_file_too_large_is_rejected(tmp_path):
    with pytest.raises(FileTooLargeError, match="too large"):
        review_source("x = 1\n" * 60_000, Path("big.py"))
    small_limits = Rules(thresholds=defaults_for("python") | {"file_max_bytes": 10})
    with pytest.raises(FileTooLargeError):
        review_source(FIVE_ARGS, Path("f.py"), small_limits)
    config_dir = tmp_path / ".codehealth"
    config_dir.mkdir()
    (config_dir / "rules.json").write_text(json.dumps({"rule_sets": [{"thresholds": [{"name": "file_max_bytes", "value": 5}]}]}))
    (tmp_path / "f.py").write_text(FIVE_ARGS)
    with pytest.raises(FileTooLargeError):
        review_file(tmp_path / "f.py")
