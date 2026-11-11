"""End-to-end reviews of the per-language fixtures."""

from __future__ import annotations

import pytest

from codehealth.analysis import review_file

from .conftest import FIXTURES

# Nesting depth comes from our tree-sitter adapters (control structures only)
# for every fixture language here; lizard's nd, which also counts &&/|| as
# nesting (it gave JS/TS/Java 6 and Go 7), is only the fallback for brace
# languages without an adapter. See DESIGN.md.
COMMON = {
    ("Complex Method", "process", 9),
    ("Complex Conditional", "process", 2),
    ("Excess Number of Function Arguments", "process", 5),
    ("Bumpy Road Ahead", "bumpy", 2),
    ("Low Cohesion", "Mixed", 2),
}

EXPECTED = {
    # The dup_* / dupOne-dupTwo pairs are renamed clones with changed literals.
    # CPD's Python/ECMAScript/TypeScript lexers do not honour --ignore-identifiers
    # or --ignore-literals; our normalized tree-sitter tokens find them (with or
    # without PMD). See test_clones.py.
    "python/smelly.py": {
        "lines": {"process": (4, 17), "bumpy": (20, 28), "Mixed": (59, 76), "dup_one / dup_two": (31, 56)},
        "extra": {("Deep, Nested Complexity", "process", 5), ("Code Duplication", "dup_one / dup_two", 100.0)},
    },
    "javascript/smelly.js": {
        "lines": {"process": (2, 21), "bumpy": (23, 36), "Mixed": (68, 84), "dupOne / dupTwo": (38, 66)},
        "extra": {("Deep, Nested Complexity", "process", 5), ("Code Duplication", "dupOne / dupTwo", 100.0)},
    },
    "typescript/smelly.ts": {
        "lines": {"process": (2, 21), "bumpy": (23, 36), "Mixed": (68, 89), "dupOne / dupTwo": (38, 66)},
        "extra": {("Deep, Nested Complexity", "process", 5), ("Code Duplication", "dupOne / dupTwo", 100.0)},
    },
    "java/Smelly.java": {
        "lines": {"Smelly.process": (8, 27), "Smelly.bumpy": (29, 42), "Smelly": (2, 59)},
        "rename": {"process": "Smelly.process", "bumpy": "Smelly.bumpy", "Mixed": "Smelly"},
        "extra": {("Deep, Nested Complexity", "Smelly.process", 5)},
    },
    "go/smelly.go": {
        "lines": {"Process": (8, 27), "Bumpy": (29, 42), "Mixed": (44, 50)},
        "rename": {"process": "Process", "bumpy": "Bumpy"},
        "extra": {("Deep, Nested Complexity", "Process", 5)},
    },
}


@pytest.mark.parametrize(
    "name", ["python/clean.py", "javascript/clean.js", "typescript/clean.ts", "tsx/clean.tsx", "java/Clean.java", "go/clean.go"]
)
def test_clean_files_score_ten(name):
    review = review_file(FIXTURES / name)
    assert review.findings == []
    assert review.score == 10.0
    assert review.category == "Healthy"


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_smelly_findings(name):
    spec = EXPECTED[name]
    rename = spec.get("rename", {})
    expected = {(smell, rename.get(fn, fn), value) for smell, fn, value in COMMON} | spec["extra"]
    review = review_file(FIXTURES / name)
    actual = {(f.smell, f.function, f.value) for f in review.findings}
    assert actual == expected
    for finding in review.findings:
        if finding.function in spec["lines"]:
            assert (finding.start_line, finding.end_line) == spec["lines"][finding.function], finding
    assert review.category == "Warning"


def test_complex_conditional_reports_line():
    review = review_file(FIXTURES / "python/smelly.py")
    cond = next(f for f in review.findings if f.smell == "Complex Conditional")
    assert cond.details["conditions"] == [{"line": 6, "operators": 2}]


def test_tsx_smelly():
    review = review_file(FIXTURES / "tsx/smelly.tsx")
    found = {(f.smell, f.function, f.value) for f in review.findings}
    assert ("Complex Method", "TaskList", 10) in found
    assert ("Deep, Nested Complexity", "TaskList", 5) in found
    assert ("Excess Number of Function Arguments", "TaskList", 5) in found
    cond = next(f for f in review.findings if f.smell == "Complex Conditional")
    assert cond.details["conditions"] == [{"line": 7, "operators": 3}]
    assert review.score < 9.0
