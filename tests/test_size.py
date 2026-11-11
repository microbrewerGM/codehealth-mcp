"""File size below the file-LoC warning lowers the score a little (score.size_units)."""

from __future__ import annotations

from pathlib import Path

import pytest

from codehealth import delta, score
from codehealth.analysis import review_source
from codehealth.config import Rules
from codehealth.thresholds import defaults_for


@pytest.fixture(autouse=True)
def _no_pmd(monkeypatch):
    # The generated functions are copies of each other; keep CPD out of these tests.
    monkeypatch.setenv("CODEHEALTH_NO_PMD", "1")


def _plain_functions(count: int) -> str:
    # 9 NLOC each: below the 10-LoC minimum of the duplication check, so the copies are not compared.
    body = "".join(f"    b{j} = a + {j}\n" for j in range(7))
    return "".join(f"def f{i}(a):\n{body}    return b0 * {i}\n\n" for i in range(count))


def test_size_units_use_published_scales():
    java, python = defaults_for("java"), defaults_for("python")
    assert score.size_units(70, java) == 0.0  # one acceptable function is free
    assert score.size_units(1070, java) == 1.0
    assert score.size_units(670, python) == 1.0  # Python's file warning is 600


def test_small_clean_file_stays_optimal_and_large_clean_file_loses_a_little():
    small = review_source(_plain_functions(2), Path("s.py"))
    big = review_source(_plain_functions(60), Path("b.py"))
    assert small.score == 10.0 and small.findings == []
    assert big.findings == [] and 9.0 <= big.score < 10.0
    assert big.to_dict()["file_size_penalty"] > 0


def test_file_loc_rule_weight_zero_disables_the_size_term():
    rules = Rules(thresholds=defaults_for("python"), weights={"Lines of Code in a Single File": 0.0})
    assert review_source(_plain_functions(60), Path("b.py"), rules).score == 10.0


def test_growing_a_clean_file_is_not_a_regression():
    result = delta.compare_sources(Path("a.py"), _plain_functions(30), _plain_functions(60))
    assert result.new_score < result.old_score
    assert result.verdict == delta.STABLE and result.gate_passed
