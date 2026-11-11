"""Delta analysis against temporary git repositories."""

from __future__ import annotations

from pathlib import Path

from codehealth import delta

from .conftest import git

CLEAN = "def f(a):\n    return a\n"
NESTED = """def f(a):
    if a:
        for x in a:
            while x:
                if x > 1:
                    x -= 1
    return a
"""


def commit_file(repo: Path, rel: str, text: str, message: str = "c") -> None:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    git(repo, "add", rel)
    git(repo, "commit", "-q", "-m", message)


def test_compare_sources_verdicts():
    degraded = delta.compare_sources(Path("a.py"), CLEAN, NESTED)
    assert degraded.verdict == "degraded" and not degraded.gate_passed
    assert ("Deep, Nested Complexity", "f") in [(f.smell, f.function) for f in degraded.new_findings]
    improved = delta.compare_sources(Path("a.py"), NESTED, CLEAN)
    assert improved.verdict == "improved" and improved.gate_passed
    assert "Deep, Nested Complexity" in [f.smell for f in improved.fixed]
    stable = delta.compare_sources(Path("a.py"), CLEAN, CLEAN + "\n")
    assert stable.verdict == "stable"


def test_worse_existing_finding_is_degraded():
    deeper = NESTED.replace("x -= 1", "if x:\n                        x -= 1")
    result = delta.compare_sources(Path("a.py"), NESTED, deeper)
    assert result.verdict == "degraded"
    assert {"smell": "Deep, Nested Complexity", "function": "f", "old": 4, "new": 5} in result.worsened


def test_unsupported_file_is_unknown():
    assert delta.compare_sources(Path("a.txt"), "x", "y").verdict == "unknown"


def test_pre_commit_safeguard(repo):
    commit_file(repo, "pkg/a.py", CLEAN)
    commit_file(repo, "notes.txt", "hi")
    clean = delta.pre_commit_safeguard(repo)
    assert clean["quality_gate"] == "passed" and clean["files"] == []
    (repo / "pkg/a.py").write_text(NESTED)
    (repo / "notes.txt").write_text("changed")
    result = delta.pre_commit_safeguard(repo)
    assert result["quality_gate"] == "failed"
    assert [f["path"] for f in result["files"]] == ["pkg/a.py"]
    assert result["files"][0]["verdict"] == "degraded"
    git(repo, "add", "pkg/a.py")  # staged changes count too
    assert delta.pre_commit_safeguard(repo)["quality_gate"] == "failed"


def test_pre_commit_on_repo_without_commits(repo):
    (repo / "a.py").write_text(NESTED)
    git(repo, "add", "a.py")
    result = delta.pre_commit_safeguard(repo)
    assert result["files"][0]["verdict"] == "degraded"
    assert result["files"][0].get("old_score") is None


def test_analyze_change_set_uses_merge_base(repo):
    commit_file(repo, "a.py", NESTED)
    commit_file(repo, "b.py", CLEAN)
    git(repo, "checkout", "-q", "-b", "feature")
    commit_file(repo, "a.py", CLEAN, "fix a")
    commit_file(repo, "c.js", "function g(a, b, c, d, e) { return a; }\n", "add c")
    git(repo, "checkout", "-q", "main")
    commit_file(repo, "b.py", NESTED, "main moves on")
    git(repo, "checkout", "-q", "feature")
    result = delta.analyze_change_set(repo, "main")
    verdicts = {f["path"]: f["verdict"] for f in result["files"]}
    assert verdicts == {"a.py": "improved", "c.js": "degraded"}
    assert result["quality_gate"] == "failed"
    assert result["merge_base"] == git(repo, "merge-base", "HEAD", "main").strip()
