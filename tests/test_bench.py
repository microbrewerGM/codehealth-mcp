"""Benchmark helpers: CSV path mapping and evaluation metrics."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bench import dataset as ds
from bench import metrics as m


def test_csv_components_drop_project_and_sourcefiles_prefix():
    path = r"aoi\sourcefiles\ArtOfIllusion\src\artofillusion\animation\ActorEditorWindow.java"
    assert ds.csv_components(path) == ["ArtOfIllusion", "src", "artofillusion", "animation", "ActorEditorWindow.java"]


def test_match_path_requires_package_suffix():
    files = ["src/main/java/org/junit/Test.java", "src/test/java/org/junit/tests/Test.java"]
    assert ds.match_path(r"junit4\sourcefiles\src\main\java\org\junit\Test.java", "org.junit.Test", files) == files[0]
    assert ds.match_path(r"junit4\sourcefiles\src\main\java\org\junit\Nope.java", "org.junit.Nope", files) is None


def test_match_path_prefers_longest_shared_tail():
    files = [
        "core-lib/es6/src/main/java/def/js/Array.java",
        "core-lib/es5/src/main/java/def/js/Array.java",
        "other/def/js/Array.java",
    ]
    es5 = r"jsweet\sourcefiles\core-lib\es5\src\main\java\def\js\Array.java"
    es6 = r"jsweet\sourcefiles\core-lib\es6\src\main\java\def\js\Array.java"
    assert ds.match_path(es5, "def.js.Array", files) == files[1]
    assert ds.match_path(es6, "def.js.Array", files) == files[0]


def test_match_path_does_not_match_partial_class_name():
    files = ["src/a/MyTest.java"]
    assert ds.match_path(r"p\sourcefiles\src\a\Test.java", "a.Test", files) is None


def test_code_loc_ignores_comments_and_blanks():
    src = "/* header\n * more\n */\npackage a;\n\n// note\nclass A { // trailing\n}\n"
    assert ds.code_loc(src) == 3


def test_classification_counts_and_scores():
    actual = [True, True, False, False, True]
    predicted = [True, False, True, False, True]
    r = m.classification(actual, predicted)
    assert (r["tp"], r["fp"], r["fn"], r["tn"]) == (2, 1, 1, 1)
    assert r["precision"] == pytest.approx(2 / 3)
    assert r["recall"] == pytest.approx(2 / 3)
    assert r["f1"] == pytest.approx(2 / 3)
    assert r["accuracy"] == pytest.approx(3 / 5)


def test_f_beta_weights_precision():
    assert m.f_beta(1.0, 0.5, 0.5) == pytest.approx(1.25 * 0.5 / (0.25 + 0.5))
    assert m.f_beta(0.0, 0.0) == 0.0


def test_auc_perfect_inverse_and_ties():
    assert m.auc([3, 4, 1, 2], [True, True, False, False]) == 1.0
    assert m.auc([1, 2, 3, 4], [True, True, False, False]) == 0.0
    assert m.auc([5, 5, 5, 5], [True, False, True, False]) == 0.5


def test_spearman_handles_ties_and_monotone():
    assert m.spearman([1, 2, 3, 4], [10, 20, 30, 400]) == pytest.approx(1.0)
    assert m.spearman([1, 2, 3, 4], [4, 3, 2, 1]) == pytest.approx(-1.0)
    assert m.rankdata([10, 20, 20, 30]) == [1.0, 2.5, 2.5, 4.0]


def test_evaluate_uc1_uc2_are_complementary():
    maint = [True, True, True, False, False]
    score = [10.0, 9.5, 8.0, 9.0, 3.0]
    ev = m.evaluate(maint, score, 9.0)
    assert ev["uc1"]["tp"] == 2 and ev["uc1"]["fp"] == 1 and ev["uc1"]["fn"] == 1
    assert ev["uc2"]["precision"] == pytest.approx(0.5)  # flagged {8.0, 3.0}, one truly bad
    assert ev["uc2"]["recall"] == pytest.approx(0.5)


def _scored(maintainable: bool, smells: list[str], size: float = 0.0):
    from bench.run_bench import Scored

    row = ds.Row("p", "a.A", "a/A.java", 0 if maintainable else 3, 10.0, 100.0, {})
    findings = [{"smell": sm, "level": "function", "function": "f", "key": f"f{i}", "severity": 1.0, "weight": 1.0}
                for i, sm in enumerate(smells)]
    return Scored(row, "A.java", 100, 0.0, findings, size)


def test_ablation_drops_one_smell_from_cached_findings():
    from bench import ablate

    files = [_scored(True, []), _scored(True, ["Low Cohesion"]), _scored(False, ["Complex Method"] * 3)]
    rows = {r["variant"]: r for r in ablate.ablate(files)}
    assert rows["none (all enabled)"]["d_f1"] == 0.0
    assert rows["smell: Complex Method"]["f1"] == 0.0  # the only bad file is no longer flagged
    assert ablate.rescore(files[1], frozenset({"Low Cohesion"})) == 10.0
    assert ablate.rescore(_scored(True, [], size=1.0), frozenset({ablate.SIZE_TERM})) == 10.0


def test_scored_cache_round_trip():
    from bench.run_bench import Scored

    item = _scored(False, ["Large Method"], size=0.5)
    assert Scored.from_dict(item.to_dict()) == item


def test_bench_data_dir_must_be_configured(monkeypatch, tmp_path):
    monkeypatch.delenv(ds.DATA_ENV, raising=False)
    with pytest.raises(SystemExit, match="CODEHEALTH_BENCH_DATA is not set"):
        ds.default_csv()
    monkeypatch.setenv(ds.DATA_ENV, str(tmp_path))
    with pytest.raises(SystemExit, match="missing .*maintainability_data.csv"):
        ds.default_csv()
    (tmp_path / "sources").mkdir()
    assert ds.default_sources() == tmp_path / "sources"
