"""Code Health score: ``1 + 9 * exp(-k * penalty)``, rounded to 2 decimals.

All scoring constants live here. They are our own design and will be
calibrated against a benchmark (see DESIGN.md).
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable

from . import smells as s
from .smells import Finding

K = 0.15  # decay constant: penalty 1.0 costs about 1.3 points
MAX_SCORE = 10.0
MIN_SCORE = 1.0
FUNCTION_PENALTY_CAP = 6.0  # one function cannot dominate the whole file
# File size below the "Lines of Code in a Single File" warning still costs a
# little: FILE_SIZE_WEIGHT per file-LoC-warning lines of NLOC beyond one
# acceptable function (``function_lines_of_code_warning``). See size_units.
FILE_SIZE_WEIGHT = 0.5

HEALTHY_MIN = 9.0
WARNING_MIN = 4.0

# Relative impact of each smell; multiplied by severity and the rule weight.
SMELL_IMPACT: dict[str, float] = {
    s.BRAIN_METHOD: 3.0,
    s.COMPLEX_METHOD: 1.0,
    s.LARGE_METHOD: 1.0,
    s.DEEP_NESTING: 1.5,
    s.BUMPY_ROAD: 1.5,
    s.COMPLEX_CONDITIONAL: 0.75,
    s.EXCESS_ARGUMENTS: 0.75,
    s.CONSTRUCTOR_OVER_INJECTION: 0.75,
    s.FILE_LOC: 2.0,
    s.FUNCTION_COUNT: 1.0,
    s.LOW_COHESION: 1.5,
    s.BRAIN_CLASS: 3.0,
    s.DUPLICATION: 1.0,
    s.OVERALL_COMPLEXITY: 1.0,
}


def finding_penalty(finding: Finding) -> float:
    return SMELL_IMPACT.get(finding.smell, 1.0) * finding.severity * finding.weight


def penalty_key(finding: Finding) -> str | None:
    """The function a penalty is capped under (None = file level).

    Keyed by stable identity, not display name, so Java overloads (same
    name) each get their own cap.
    """
    if finding.level != "function":
        return None
    return finding.identity or finding.function or ""


def capped_total(penalties: Iterable[tuple[str | None, float]], cap: float = FUNCTION_PENALTY_CAP) -> float:
    """Sum ``(function key, penalty)`` pairs; key None means file level (uncapped)."""
    per_function: dict[str, float] = defaultdict(float)
    file_level = 0.0
    for key, penalty in penalties:
        if key is None:
            file_level += penalty
        else:
            per_function[key] += penalty
    return file_level + sum(min(p, cap) for p in per_function.values())


def total_penalty(findings: Iterable[Finding]) -> float:
    return capped_total((penalty_key(f), finding_penalty(f)) for f in findings)


def size_units(lines_of_code: float, thresholds: dict[str, float]) -> float:
    """File NLOC beyond one acceptable function, in units of the file LoC warning threshold.

    Both scales are the published default thresholds of the file's language (Java: 70 and
    1000, Python: 70 and 600), so the thresholds themselves are unchanged; only
    their contribution to the score is ours.
    """
    allowance = thresholds["function_lines_of_code_warning"]
    return max(0.0, lines_of_code - allowance) / thresholds["file_lines_of_code_for_warning"]


def score_from_penalty(penalty: float) -> float:
    return round(MIN_SCORE + (MAX_SCORE - MIN_SCORE) * math.exp(-K * penalty), 2)


def code_health(findings: Iterable[Finding], size: float = 0.0) -> float:
    """Score from the findings plus ``size`` (from :func:`size_units`, times the file LoC rule weight)."""
    return score_from_penalty(total_penalty(findings) + FILE_SIZE_WEIGHT * size)


def category(score: float) -> str:
    if score >= HEALTHY_MIN:
        return "Healthy"
    if score >= WARNING_MIN:
        return "Warning"
    return "Alert"


def is_optimal(score: float) -> bool:
    return score >= MAX_SCORE
