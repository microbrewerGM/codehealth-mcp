"""PMD integration: report parsing (recorded samples, no Java needed), graceful
degradation, analyzer-availability reporting, and PMD-marked integration tests."""

from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest

from codehealth import analysis, delta, enrich, pmd
from codehealth.analysis import measure_source, review_file, review_source
from codehealth.duplication import map_duplications
from codehealth.smells import ExternalResults, detect
from codehealth.thresholds import defaults_for

from .conftest import FIXTURES, git

SAMPLES = FIXTURES / "pmd"


@pytest.fixture
def no_pmd(monkeypatch):
    monkeypatch.setenv("CODEHEALTH_NO_PMD", "1")


# ----- parsing recorded reports ----------------------------------------------------------
def test_parse_cpd_xml_sample():
    [dup] = pmd.parse_cpd_xml((SAMPLES / "cpd_sample.xml").read_text())
    assert (dup.lines, dup.tokens) == (13, 64)
    assert [(o.path, o.start_line, o.end_line) for o in dup.occurrences] == [
        ("/work/a.js", 1, 13),
        ("/work/a.js", 15, 27),
        ("/work/b.js", 1, 13),
    ]


def test_parse_cpd_xml_refuses_entities():
    evil = '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY e "boom">]><pmd-cpd>&e;</pmd-cpd>'
    with pytest.raises(pmd.PmdError):
        pmd.parse_cpd_xml(evil)
    assert pmd.parse_cpd_xml("") == []


def test_map_cpd_sample_onto_functions():
    dups = pmd.parse_cpd_xml((SAMPLES / "cpd_sample.xml").read_text())
    limits = defaults_for("javascript")
    functions = {
        f"/work/{name}": measure_source((SAMPLES / name).read_text(), Path(name), limits).metrics.functions
        for name in ("a.js", "b.js")
    }
    pairs = map_duplications(dups, functions, 10, 0.75)
    found = [(p.first_path, p.pair.first.name, p.second_path, p.pair.second.name, p.pair.similarity) for p in pairs]
    assert found == [
        ("/work/a.js", "sumEven", "/work/a.js", "sumEvenAgain", 1.0),
        ("/work/a.js", "sumEven", "/work/b.js", "copied", 1.0),
        ("/work/a.js", "sumEvenAgain", "/work/b.js", "copied", 1.0),
    ]
    assert map_duplications(dups, functions, 50, 0.75) == []  # functions below the minimum size


def test_parse_pmd_json_and_god_class_maps_to_brain_class():
    violations = pmd.parse_pmd_json((SAMPLES / "pmd_sample.json").read_text())
    [god] = violations
    assert god.rule == "GodClass" and god.begin_line == 4
    assert pmd.god_class_metrics(god.message) == {"wmc": 56, "atfd": 72, "tcc_percent": 0.0}
    source = (FIXTURES / "java" / "GodClass.java").read_text()
    m = measure_source(source, Path("GodClass.java"), defaults_for("java"))
    external = ExternalResults(duplicates=[], god_classes=enrich.god_classes(violations, m.parsed))
    [brain] = [f for f in detect(m, defaults_for("java"), external) if f.smell == "Brain Class"]
    assert (brain.function, brain.identity, brain.value, brain.threshold) == ("Ledger", "Ledger", 56, 47)
    assert brain.details["provider"] == "pmd:GodClass"


def test_other_pmd_rules_attach_as_details_without_penalty():
    review = review_source("def f(a, b, c, d, e):\n    return a\n", Path("x.py"))
    before = review.score
    rule = pmd.Violation("ExcessiveParameterList", 1, 1, "Avoid long parameter lists.", 3)
    analysis._attach_violations(review.findings, [rule])
    assert review.findings[0].details["pmd"] == [rule.to_dict()]
    assert before == review.score


# ----- degradation and availability reporting -----------------------------------------------
def test_pmd_disabled_reports_unavailable_smells(no_pmd):
    review = review_file(FIXTURES / "python" / "smelly.py")
    data = review.to_dict()["analyzers"]
    assert data["pmd"] == {"ran": False, "reason": "disabled by CODEHEALTH_NO_PMD"}
    assert data["unavailable_smells"] == []  # renamed-clone tokens cover Python without PMD
    assert data["lizard"]["ran"] and data["lizard"]["version"].startswith("1.26")
    assert data["tree_sitter"] == {"ran": True}
    java = review_file(FIXTURES / "java" / "Smelly.java").analyzers
    assert java["unavailable_smells"] == ["Brain Class", "Code Duplication"]


def test_missing_pmd_home_and_missing_java(monkeypatch, tmp_path):
    monkeypatch.delenv("CODEHEALTH_NO_PMD", raising=False)
    monkeypatch.setenv("CODEHEALTH_PMD_HOME", str(tmp_path))
    assert pmd.locate() == (None, "PMD not found; run `codehealth install-pmd` or set CODEHEALTH_PMD_HOME")
    home = tmp_path / "pmd-bin-7.0.0"
    (home / "bin").mkdir(parents=True)
    (home / "bin" / "pmd").write_text("#!/bin/sh\nexit 0\n")
    monkeypatch.setattr(pmd, "_java", lambda: None)
    install, reason = pmd.locate()
    assert install is None and "Java runtime not found" in reason
    review = review_file(FIXTURES / "python" / "clean.py")
    assert review.score == 10.0 and review.analyzers["pmd"]["ran"] is False


def test_failing_pmd_never_fails_the_tool(monkeypatch, tmp_path):
    monkeypatch.delenv("CODEHEALTH_NO_PMD", raising=False)
    home = tmp_path / "pmd-bin-7.0.0"
    (home / "bin").mkdir(parents=True)
    script = home / "bin" / "pmd"
    script.write_text("#!/bin/sh\necho 'boom' >&2\nexit 2\n")
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("CODEHEALTH_PMD_HOME", str(home))
    monkeypatch.setenv("CODEHEALTH_CACHE_DIR", str(tmp_path / "cache"))
    review = review_file(FIXTURES / "java" / "Smelly.java")
    assert review.analyzers["pmd"]["ran"] is False
    assert "status 2" in review.analyzers["pmd"]["reason"]
    assert "Code Duplication" in review.analyzers["unavailable_smells"]
    assert {f.smell for f in review.findings} >= {"Complex Method", "Low Cohesion"}
    assert not any((tmp_path / "cache" / "work").iterdir())  # scratch copies are removed


def test_scratch_paths_refuse_traversal(tmp_path):
    for bad in ("../x.py", "/abs.py", "a/../../b.py", ""):
        with pytest.raises(ValueError):
            pmd.write_sources(tmp_path, {bad: "x"})


# ----- other languages ----------------------------------------------------------------------
def test_ruby_file_is_reviewable(no_pmd):
    review = review_file(FIXTURES / "ruby" / "smelly.rb")
    found = {(f.smell, f.function, f.value) for f in review.findings}
    assert found == {
        ("Complex Method", "charge", 10),
        ("Excess Number of Function Arguments", "charge", 5),
        ("Constructor Over-Injection", "initialize", 6),
        ("Overall Code Complexity", None, 5.5),
    }
    unavailable = review.analyzers["unavailable_smells"]
    assert {"Bumpy Road Ahead", "Complex Conditional", "Low Cohesion", "Deep, Nested Complexity", "Brain Method"} <= set(unavailable)
    assert review.analyzers["unavailable_features"] == ["comment directives"]


def test_csharp_file_is_reviewable(no_pmd):
    review = review_file(FIXTURES / "csharp" / "Smelly.cs")
    found = {(f.smell, f.function, f.value) for f in review.findings}
    assert ("Deep, Nested Complexity", "Demo.Billing.Charge", 6) in found  # lizard nd works for braces
    assert ("Constructor Over-Injection", "Demo.Billing.Billing", 6) in found
    assert "Deep, Nested Complexity" not in review.analyzers["unavailable_smells"]
    assert review.category == "Warning"


# ----- integration (needs PMD + Java) -------------------------------------------------------
@pytest.mark.pmd
def test_cpd_finds_within_file_copy():
    source = (SAMPLES / "a.js").read_text()
    review = review_source(source, Path("a.js"))
    [dup] = [f for f in review.findings if f.smell == "Code Duplication"]
    assert (dup.function, dup.value, dup.details["provider"]) == ("sumEven / sumEvenAgain", 100.0, "pmd:cpd")
    assert review.analyzers["pmd"]["ran"] is True and "cpd" in review.analyzers["pmd"]["tools"]


@pytest.mark.pmd
def test_java_god_class_from_pmd():
    review = review_file(FIXTURES / "java" / "GodClass.java")
    [brain] = [f for f in review.findings if f.smell == "Brain Class"]
    assert brain.function == "Ledger" and brain.details["wmc"] >= 47
    assert any(v["rule"] == "GodClass" for v in review.to_dict()["pmd_violations"])


@pytest.mark.pmd
def test_cross_file_duplication_in_precommit(repo):
    (repo / "a.js").write_text("// a\n")
    (repo / "b.js").write_text("// b\n")
    git(repo, "add", "a.js", "b.js")
    git(repo, "commit", "-q", "-m", "init")
    (repo / "a.js").write_text((SAMPLES / "b.js").read_text())
    (repo / "b.js").write_text((SAMPLES / "b.js").read_text().replace("copied", "again"))
    result = delta.pre_commit_safeguard(repo)
    assert result["analyzers"]["cross_file_cpd"]["ran"] is True
    [entry] = result["cross_file_duplication"]
    assert (entry["first"]["path"], entry["second"]["path"], entry["similarity"]) == ("a.js", "b.js", 100.0)
    assert json.dumps(result)  # serialisable


# ----- batching: one JVM per tool for many files ------------------------------------------
def _count_runs(monkeypatch) -> list[list[str]]:
    calls: list[list[str]] = []
    real = pmd._run

    def counting(install, args, files=1):
        calls.append(args)
        return real(install, args, files)

    monkeypatch.setattr(pmd, "_run", counting)
    return calls


@pytest.mark.pmd
def test_batch_runs_each_tool_once_and_matches_single_file_reviews(monkeypatch):
    js = (SAMPLES / "a.js").read_text()
    java = (FIXTURES / "java" / "GodClass.java").read_text()
    smelly = (FIXTURES / "java" / "Smelly.java").read_text()
    requests = [
        analysis.ReviewRequest(js, Path("a.js")),
        analysis.ReviewRequest(js, Path("copy/a.js")),  # same name, other directory
        analysis.ReviewRequest(java, Path("GodClass.java")),
        analysis.ReviewRequest(smelly, Path("Smelly.java")),
    ]
    singles = [review_source(r.source, r.path) for r in requests]
    calls = _count_runs(monkeypatch)
    batch = analysis.review_sources(requests)
    tools = sorted(args[0] for args in calls)
    assert tools.count("check") == 1  # both Java files in one PMD check
    assert len(calls) <= 3  # CPD once per lexer group (ecmascript, java) + one check
    for one, many in zip(singles, batch):
        assert many.to_dict() == one.to_dict()
    # Identical files never produce cross-file pairs in per-file results.
    assert [f.function for f in batch[1].findings if f.smell == "Code Duplication"] == ["sumEven / sumEvenAgain"]


@pytest.mark.pmd
def test_batch_failure_degrades_every_file(monkeypatch):
    def boom(*args, **kwargs):
        raise pmd.PmdError("PMD exited with status 2: boom")

    monkeypatch.setattr(pmd, "run_cpd", boom)
    js = (SAMPLES / "a.js").read_text()
    reviews = analysis.review_sources([analysis.ReviewRequest(js, Path("a.js")), analysis.ReviewRequest(js, Path("b.js"))])
    for review in reviews:
        assert review.analyzers["pmd"]["ran"] is False and "boom" in review.analyzers["pmd"]["reason"]
        # JavaScript copies still come from normalized tree-sitter tokens.
        assert "Code Duplication" not in review.analyzers["unavailable_smells"]
        assert [f.details["provider"] for f in review.findings if f.smell == "Code Duplication"] == ["tree-sitter:tokens"]


def test_batch_returns_errors_in_place(no_pmd):
    reviews = analysis.review_sources([
        analysis.ReviewRequest("def f():\n    return 1\n", Path("ok.py")),
        analysis.ReviewRequest("x", Path("notes.txt")),
    ])
    assert reviews[0].score == 10.0
    assert isinstance(reviews[1], ValueError)


def test_batch_timeout_scales_with_file_count(monkeypatch):
    monkeypatch.setenv("CODEHEALTH_PMD_TIMEOUT", "10")
    assert pmd._timeout() == 10 and pmd._timeout(100) == 10 and pmd._timeout(101) == 20
