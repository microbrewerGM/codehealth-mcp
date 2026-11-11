"""Rules files, glob matching and comment directives."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from codehealth import config
from codehealth.analysis import review_file, review_source

from .conftest import FIXTURES


def write_rules(root: Path, rule_sets: list[dict], rel: str = ".codehealth/rules.json") -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"rule_sets": rule_sets}))
    return path


@pytest.mark.parametrize(
    ("pattern", "path", "ok"),
    [
        ("**/*", "a.py", True),
        ("**/*", "src/a/b.py", True),
        ("**/*.js", "src/a.js", True),
        ("**/*.js", "src/a.py", False),
        ("test/**", "test/x/y.py", True),
        ("test/**", "src/test/y.py", False),
        ("src/*.py", "src/a/b.py", False),
    ],
)
def test_glob_match(pattern, path, ok):
    assert config.glob_match(pattern, path) is ok


def smelly_copy(repo: Path) -> Path:
    target = repo / "src" / "smelly.py"
    target.parent.mkdir(parents=True)
    shutil.copy(FIXTURES / "python" / "smelly.py", target)
    return target


def test_weight_zero_disables_and_threshold_override(repo):
    target = smelly_copy(repo)
    write_rules(repo, [{
        "matching_content_path": "src/**",
        "rules": [{"name": "Code Duplication", "weight": 0.0}, {"name": "Low Cohesion", "weight": 0.5}],
        "thresholds": [{"name": "function_max_arguments", "value": 5}],
    }])
    review = review_file(target)
    smells = {f.smell: f for f in review.findings}
    assert "Code Duplication" not in smells
    assert "Excess Number of Function Arguments" not in smells
    assert smells["Low Cohesion"].weight == 0.5
    assert review.score > review_file(FIXTURES / "python" / "smelly.py").score


def test_only_first_matching_rule_set_applies(repo):
    target = smelly_copy(repo)
    write_rules(repo, [
        {"matching_content_path": "**/*.py", "rules": [{"name": "Bumpy Road Ahead", "weight": 0}]},
        {"matching_content_path": "**/*", "rules": [{"name": "Low Cohesion", "weight": 0}]},
    ])
    smells = {f.smell for f in review_file(target).findings}
    assert "Bumpy Road Ahead" not in smells
    assert "Low Cohesion" in smells


def test_codehealth_rules_path_is_accepted(repo):
    target = smelly_copy(repo)
    write_rules(repo, [{"rules": [{"name": "Low Cohesion", "weight": 0}]}], rel=".codehealth/rules.json")
    assert "Low Cohesion" not in {f.smell for f in review_file(target).findings}


def test_invalid_config_is_reported(repo):
    target = smelly_copy(repo)
    write_rules(repo, [{"rules": [{"name": "No Such Rule", "weight": 1}], "thresholds": [{"name": "bogus", "value": 1}]}])
    with pytest.raises(config.ConfigError, match="No Such Rule"):
        review_file(target)
    errors = config.validate_config({"rule_sets": [{"thresholds": [{"name": "function_max_arguments", "value": -1}]}]})
    assert errors and "non-negative" in errors[0]


def test_set_entry_creates_and_updates(repo):
    path = config.set_rule(repo, "Large Method", 0.0)
    config.set_threshold(repo, "function_nesting_depth_warning", 6, "test/**")
    config.set_rule(repo, "Large Method", 0.5)
    data = json.loads(path.read_text())
    assert path == repo / ".codehealth" / "rules.json"
    assert [rs["matching_content_path"] for rs in data["rule_sets"]] == ["test/**", "**/*"]
    assert data["rule_sets"][1]["rules"] == [{"name": "Large Method", "weight": 0.5}]
    with pytest.raises(config.ConfigError):
        config.set_threshold(repo, "not_a_threshold", 1)


DIRECTIVE_SRC = '''class C:
    # @codehealth(disable:"Excess Number of Function Arguments")
    def many(self, a, b, c, d, e):
        return a


# @codehealth(disable-all)
def nested(a, b, c, d, e):
    if a:
        if b:
            if c:
                if d:
                    return e


def still_flagged(a, b, c, d, e):
    return a
'''


def test_directives_apply_to_next_function_only():
    review = review_source(DIRECTIVE_SRC, Path("d.py"))
    flagged = {(f.smell, f.function) for f in review.findings}
    assert ("Excess Number of Function Arguments", "still_flagged") in flagged
    assert not any(fn in ("C.many", "nested") for _, fn in flagged)


def test_file_level_smells_cannot_be_disabled():
    # Low Cohesion is file level and measured without PMD (Code Duplication now needs PMD).
    src = "# @codehealth(disable:\"Low Cohesion\")\n" + (FIXTURES / "python" / "smelly.py").read_text()
    review = review_source(src, Path("s.py"))
    assert "Low Cohesion" in {f.smell for f in review.findings}


def test_directives_work_in_js_and_java():
    js = "// @codehealth(disable:\"Excess Number of Function Arguments\")\nfunction f(a, b, c, d, e) { return a; }\n"
    assert review_source(js, Path("x.js")).findings == []
    java = "class A {\n  /* @codehealth(disable-all) */\n  void f(int a, int b, int c, int d, int e) {}\n}\n"
    assert review_source(java, Path("A.java")).findings == []
