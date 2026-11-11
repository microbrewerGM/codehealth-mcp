"""Default thresholds for every metric, in one table.

Provenance: rows with ``published=True`` (marked ``# published default``)
take their names and values from publicly documented default rule
thresholds of a widely used Code Health model; see "Influences and
acknowledgements" in README.md. Rows marked ``inferred`` are our own choices
where no published number exists; they are calibrated on the benchmark in
``bench/``.

``OPERATORS`` states how a measured value is compared with its threshold.
"""

from __future__ import annotations

from dataclasses import dataclass

GE = ">="
GT = ">"


@dataclass(frozen=True)
class Threshold:
    name: str
    default: float
    operator: str
    published: bool
    description: str


_TABLE: tuple[Threshold, ...] = (
    # --- published defaults (baseline = java/js template) ---
    Threshold("constructor_max_arguments", 5, GT, True, "Constructor arguments"),  # published default
    Threshold("file_lines_of_code_for_warning", 1000, GT, True, "File lines of code, warning"),  # published default
    Threshold("file_lines_of_code_for_alert", 5000, GT, True, "File lines of code, alert"),  # published default
    Threshold("file_lines_of_code_for_critical_alert", 10000, GT, True, "File lines of code, critical"),  # published default
    Threshold("file_mean_cyclomatic_complexity_warning", 4, GE, True, "Mean cyclomatic complexity per function"),  # published default
    Threshold("file_primitive_obsession_percentage_for_warning", 30, GE, True, "Primitive argument percentage (not yet measured)"),  # published default
    Threshold("function_bumpy_road_bumps_for_warning", 2, GE, True, "Bumps in one function"),  # published default
    Threshold("function_bumpy_road_nesting_level_depth", 2, GE, True, "Nesting depth that makes a chunk a bump"),  # published default
    Threshold("function_complex_conditional_branches_warning", 2, GE, True, "Logical operators in one condition"),  # published default
    Threshold("function_complex_conditional_branches_alert", 10, GE, True, "Logical operators in one condition, alert"),  # published default
    Threshold("function_cyclomatic_complexity_warning", 9, GE, True, "Cyclomatic complexity, warning"),  # published default
    Threshold("function_cyclomatic_complexity_alert", 100, GE, True, "Cyclomatic complexity, alert"),  # published default
    Threshold("function_duplication_min_lines_of_code_for_check", 10, GE, True, "Minimum function size checked for duplication"),  # published default
    Threshold("function_duplication_min_similarity_percentage", 75, GE, True, "Similarity percentage that counts as duplicate"),  # published default
    Threshold("function_lines_of_code_warning", 70, GT, True, "Function lines of code, warning"),  # published default
    Threshold("function_lines_of_code_alert", 500, GT, True, "Function lines of code, alert"),  # published default
    Threshold("function_max_arguments", 4, GT, True, "Function arguments"),  # published default
    Threshold("function_nesting_depth_warning", 4, GE, True, "Nesting depth of control structures"),  # published default
    Threshold("unit_test_consecutive_asserts_for_large_block", 4, GE, True, "Consecutive asserts (not yet measured)"),  # published default
    Threshold("unit_test_suite_number_of_large_assertion_blocks", 4, GE, True, "Large assertion blocks (not yet measured)"),  # published default
    # --- inferred: no published value exists; our own names and numbers ---
    Threshold("file_function_count_warning", 75, GE, False, "Functions in one file"),  # inferred
    Threshold("function_duplication_min_tokens", 50, GE, False, "Minimum duplicated tokens passed to PMD CPD"),  # inferred
    Threshold("class_lcom4_warning", 2, GE, False, "LCOM4 connected components of one class"),  # inferred
    Threshold("class_lcom4_min_methods", 4, GE, False, "Minimum methods before cohesion is checked"),  # inferred
    Threshold("brain_class_lines_of_code", 400, GE, False, "Brain Class: minimum lines of code"),  # inferred
    Threshold("brain_class_function_count", 15, GE, False, "Brain Class: minimum number of functions"),  # inferred
    Threshold("file_max_bytes", 2_000_000, GT, False, "Largest file analyzed, in bytes"),  # inferred: resource guard
    Threshold("file_max_lines", 50_000, GT, False, "Largest file analyzed, in lines"),  # inferred: resource guard
)

DEFAULTS: dict[str, float] = {t.name: t.default for t in _TABLE}
OPERATORS: dict[str, str] = {t.name: t.operator for t in _TABLE}
PUBLISHED: dict[str, bool] = {t.name: t.published for t in _TABLE}
DESCRIPTIONS: dict[str, str] = {t.name: t.description for t in _TABLE}

# Severity reaches 1.0 when a value hits the alert tier of its warning threshold.
ALERT_TIER: dict[str, str] = {
    "function_cyclomatic_complexity_warning": "function_cyclomatic_complexity_alert",
    "function_lines_of_code_warning": "function_lines_of_code_alert",
    "function_complex_conditional_branches_warning": "function_complex_conditional_branches_alert",
    "file_lines_of_code_for_warning": "file_lines_of_code_for_alert",
}

_FILE_LOC_600 = {
    "file_lines_of_code_for_warning": 600,  # published default
    "file_lines_of_code_for_alert": 3000,  # published default
    "file_lines_of_code_for_critical_alert": 6000,  # published default
}

# Per-language differences from the baseline, keyed by language name.
LANGUAGE_OVERRIDES: dict[str, dict[str, float]] = {
    "python": dict(_FILE_LOC_600),
    "kotlin": dict(_FILE_LOC_600),
    "scala": dict(_FILE_LOC_600),
    "ruby": {
        "file_lines_of_code_for_warning": 600,  # published default
        "file_lines_of_code_for_alert": 3000,  # published default
        "file_lines_of_code_for_critical_alert": 5500,  # published default
    },
    "go": {
        "file_mean_cyclomatic_complexity_warning": 5,  # published default
        "file_primitive_obsession_percentage_for_warning": 40,  # published default
        "function_cyclomatic_complexity_alert": 150,  # published default
        "function_lines_of_code_warning": 80,  # published default
    },
    "perl": {
        "file_mean_cyclomatic_complexity_warning": 5,  # published default
        "function_cyclomatic_complexity_alert": 150,  # published default
        "function_lines_of_code_warning": 80,  # published default
    },
    "clojure": {
        "file_lines_of_code_for_warning": 400,  # published default
        "file_lines_of_code_for_alert": 2000,  # published default
        "file_lines_of_code_for_critical_alert": 4000,  # published default
        "function_cyclomatic_complexity_warning": 8,  # published default
        "function_cyclomatic_complexity_alert": 30,  # published default
        "function_lines_of_code_warning": 50,  # published default
        "function_lines_of_code_alert": 200,  # published default
        "unit_test_consecutive_asserts_for_large_block": 6,  # published default
    },
    "elixir": {
        "function_embedded_content_lines_of_code_warning": 100,  # published default
        "function_embedded_content_lines_of_code_alert": 600,  # published default
    },
    "javascript": {},  # published default (js template equals the baseline)
    "java": {},  # published default (baseline)
    "typescript": {},  # inferred: no ts template, uses the js values
    "tsx": {},  # inferred: no ts template, uses the js values
}


def has_template(language: str) -> bool:
    """True when ``language`` has its own threshold template; others use the baseline."""
    return language in LANGUAGE_OVERRIDES


def defaults_for(language: str) -> dict[str, float]:
    """Return the default thresholds with the overrides for ``language`` applied."""
    values = dict(DEFAULTS)
    values.update(LANGUAGE_OVERRIDES.get(language, {}))
    return values


def is_known(name: str) -> bool:
    return name in DEFAULTS or any(name in o for o in LANGUAGE_OVERRIDES.values())


def exceeds(name: str, value: float, threshold: float) -> bool:
    """Compare ``value`` with ``threshold`` using the operator for ``name``."""
    if OPERATORS.get(name, GE) == GT:
        return value > threshold
    return value >= threshold
