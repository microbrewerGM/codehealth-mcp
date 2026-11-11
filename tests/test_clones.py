"""Renamed (type-2) clones from normalized tree-sitter tokens, merged with CPD."""

from __future__ import annotations

from pathlib import Path

import pytest

from codehealth import delta
from codehealth.analysis import measure_source, review_file, review_source
from codehealth.duplication import Limits, candidates, normalized_tokens, token_pairs
from codehealth.thresholds import defaults_for

from .conftest import FIXTURES, git

CLONES = FIXTURES / "clones"
RENAMED = {
    "renamed.py": ("summarize / tally", 5, 19),
    "renamed.js": ("summarize / tally", 4, 20),
    "renamed.ts": ("summarize / tally", 7, 23),
    "renamed.tsx": ("OrderList / EventList", 6, 26),
    "renamed.go": ("one / two", 4, 19),
}


def _duplications(review):
    return [f for f in review.findings if f.smell == "Code Duplication"]


@pytest.mark.parametrize("name", sorted(RENAMED))
def test_renamed_copy_detected_and_different_function_is_not(name):
    label, start, other = RENAMED[name]
    [dup] = _duplications(review_file(CLONES / name))  # a structurally different function pairs with nothing
    assert (dup.function, dup.start_line, dup.details["other_start_line"]) == (label, start, other)
    assert dup.value >= 75 and dup.details["provider"] == "tree-sitter:tokens"


@pytest.mark.parametrize("no_pmd", ["0", "1"])
def test_renamed_clones_do_not_need_pmd(monkeypatch, no_pmd):
    monkeypatch.setenv("CODEHEALTH_NO_PMD", no_pmd)
    review = review_file(CLONES / "renamed.py")
    assert [f.function for f in _duplications(review)] == ["summarize / tally"]
    assert "Code Duplication" not in review.analyzers["unavailable_smells"]


def test_tokens_normalize_identifiers_and_literals_and_drop_comments():
    source = 'def f(a):\n    # note\n    return a + "x" + 3 + True\n'
    m = measure_source(source, Path("x.py"), defaults_for("python"))
    tokens = normalized_tokens(m.parsed, m.parsed.functions[0].node)
    assert tokens == ["def", "ID", "(", "ID", ")", ":", "return", "ID", "+", "LIT", "+", "LIT", "+", "LIT"]


def test_short_functions_are_not_compared():
    body = "    x = a + 1\n    y = x * 2\n    return y\n"
    source = f"def f(a):\n{body}\n\ndef g(b):\n{body}"
    m = measure_source(source, Path("x.py"), defaults_for("python"))
    assert token_pairs(candidates("x.py", m.parsed, m.metrics.functions, 10), Limits(10, 0.75), 50) == []


def test_functions_that_are_mostly_one_literal_are_not_reported():
    # Test boilerplate: many lines, but nearly all of them one source string.
    lines = "".join(f"    line {i}\n" for i in range(12))
    source = "".join(f'def test_{name}():\n    src = """\n{lines}"""\n    assert check(src) == {i}\n\n\n' for i, name in enumerate("ab"))
    review = review_source(source, Path("test_x.py"))
    assert [f for f in review.findings if f.smell == "Code Duplication"] == []


@pytest.mark.pmd
def test_exact_copy_reported_once_by_cpd():
    [dup] = _duplications(review_file(CLONES / "exact.py"))
    assert (dup.function, dup.value, dup.details["provider"]) == ("first_copy / second_copy", 100.0, "pmd:cpd")


def test_exact_copy_reported_once_without_pmd(monkeypatch):
    monkeypatch.setenv("CODEHEALTH_NO_PMD", "1")
    [dup] = _duplications(review_file(CLONES / "exact.py"))
    assert (dup.function, dup.value, dup.details["provider"]) == ("first_copy / second_copy", 100.0, "tree-sitter:tokens")


def test_cross_file_renamed_clone_in_change_set(repo):
    source = (CLONES / "renamed.py").read_text()
    (repo / "README").write_text("x\n")
    git(repo, "add", "README")
    git(repo, "commit", "-q", "-m", "init")
    git(repo, "checkout", "-q", "-b", "feature")
    (repo / "orders.py").write_text(source.split("\n\n\ndef tally")[0] + "\n")
    (repo / "events.py").write_text("def tally" + source.split("\n\n\ndef tally")[1].split("\n\n\ndef render")[0] + "\n")
    git(repo, "add", "orders.py", "events.py")
    git(repo, "commit", "-q", "-m", "copies")
    result = delta.analyze_change_set(repo, "main")
    [entry] = result["cross_file_duplication"]
    sides = {(entry["first"]["path"], entry["first"]["function"]), (entry["second"]["path"], entry["second"]["function"])}
    assert sides == {("orders.py", "summarize"), ("events.py", "tally")}
    assert entry["provider"] == "tree-sitter:tokens" and entry["similarity"] >= 75
    assert result["analyzers"]["cross_file_renamed_clones"]["ran"] is True
    assert result["quality_gate"] == "passed"  # informational only
