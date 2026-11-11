"""Smell detectors: turn metrics plus thresholds into findings."""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field

from . import thresholds as th
from .lang.base import ClassInfo
from .metrics import FunctionMetrics, Measured

# Rule names as used in rules files.
COMPLEX_METHOD = "Complex Method"
LARGE_METHOD = "Large Method"
BUMPY_ROAD = "Bumpy Road Ahead"
DEEP_NESTING = "Deep, Nested Complexity"
COMPLEX_CONDITIONAL = "Complex Conditional"
EXCESS_ARGUMENTS = "Excess Number of Function Arguments"
CONSTRUCTOR_OVER_INJECTION = "Constructor Over-Injection"
BRAIN_METHOD = "Brain Method"
FILE_LOC = "Lines of Code in a Single File"
FUNCTION_COUNT = "Number of Functions in a Single Module"
LOW_COHESION = "Low Cohesion"
BRAIN_CLASS = "Brain Class"
DUPLICATION = "Code Duplication"
OVERALL_COMPLEXITY = "Overall Code Complexity"

FUNCTION_LEVEL_SMELLS = frozenset(
    {
        COMPLEX_METHOD,
        LARGE_METHOD,
        BUMPY_ROAD,
        DEEP_NESTING,
        COMPLEX_CONDITIONAL,
        EXCESS_ARGUMENTS,
        CONSTRUCTOR_OVER_INJECTION,
        BRAIN_METHOD,
    }
)
FILE_LEVEL_SMELLS = frozenset({FILE_LOC, FUNCTION_COUNT, LOW_COHESION, BRAIN_CLASS, DUPLICATION, OVERALL_COMPLEXITY})

# Every rule name a rules file may weight. Names we do not detect yet are accepted.
KNOWN_RULES = FUNCTION_LEVEL_SMELLS | FILE_LEVEL_SMELLS | frozenset(
    {
        "Deep, Global Nested Complexity",
        "Duplicated Assertion Blocks",
        "Global Conditionals",
        "Large Assertion Blocks",
        "Large Embedded Code Block",
        "Lines of Declarations in a Single File",
        "Missing Arguments Abstractions",
        "Overall Function Size",
        "Primitive Obsession",
        "String Heavy Function Arguments",
    }
)

HINTS = {
    COMPLEX_METHOD: "Split the function along its decision points; move each branch body into a well-named helper.",
    LARGE_METHOD: "Extract cohesive steps into helper functions so the main function reads as a short sequence.",
    BUMPY_ROAD: "Each nested chunk is a missing abstraction; extract every bump into its own function.",
    DEEP_NESTING: "Use guard clauses and early returns, or extract the inner blocks, to flatten the nesting.",
    COMPLEX_CONDITIONAL: "Name the condition: move the boolean expression into a variable or predicate function.",
    EXCESS_ARGUMENTS: "Group arguments that travel together into an object, or split the function's responsibilities.",
    CONSTRUCTOR_OVER_INJECTION: "The class has many collaborators; split it or group related dependencies.",
    BRAIN_METHOD: "This function concentrates too much behaviour; decompose it into smaller, single-purpose functions.",
    FILE_LOC: "Split the file into smaller modules along its responsibilities.",
    FUNCTION_COUNT: "Move groups of related functions into their own modules.",
    LOW_COHESION: "The class has independent groups of methods and fields; split it into one class per group.",
    BRAIN_CLASS: "Break the module up: start by decomposing its Brain Methods, then split by responsibility.",
    DUPLICATION: "Extract the shared logic into one function and call it from both places.",
    OVERALL_COMPLEXITY: "Reduce branching across the file; simplify the most complex functions first.",
}

# A value at this multiple of its warning threshold gets severity 1.0 when no alert tier exists.
DEFAULT_SEVERITY_SPAN = 4.0
MIN_SEVERITY = 0.2


@dataclass
class Finding:
    smell: str
    level: str  # "function" or "file"
    function: str | None
    start_line: int | None  # None for findings about the whole file
    end_line: int | None
    value: float
    threshold: float
    severity: float
    message: str
    hint: str
    weight: float = 1.0
    details: dict = field(default_factory=dict)
    # Stable identity of the function/class (scope + ordinal), used to match
    # findings across versions; ``function`` is only the display name.
    identity: str | None = None

    @property
    def key(self) -> tuple[str, str | None]:
        return (self.smell, self.identity if self.identity is not None else self.function)

    def to_dict(self) -> dict:
        data = asdict(self)
        del data["identity"]
        if not data["details"]:
            del data["details"]
        if data["weight"] == 1.0:
            del data["weight"]
        return data


def severity(value: float, threshold: float, alert: float | None = None) -> float:
    """Log-scaled excess over the threshold, in (0, 1]."""
    if threshold <= 0:
        return 1.0
    span = alert / threshold if alert and alert > threshold else DEFAULT_SEVERITY_SPAN
    ratio = max(value / threshold, 1.0)
    return round(min(1.0, MIN_SEVERITY + (1 - MIN_SEVERITY) * math.log(ratio) / math.log(span)), 3)


@dataclass(frozen=True)
class DuplicatePair:
    """Two functions reported as copies of each other (see codehealth.duplication)."""

    first: FunctionMetrics
    second: FunctionMetrics
    similarity: float  # share of the larger function covered by the duplicated block, 0..1
    lines: int
    tokens: int
    provider: str = "pmd:cpd"  # or "tree-sitter:tokens" for renamed clones


@dataclass(frozen=True)
class GodClass:
    """A PMD GodClass violation, mapped onto a class (Java only)."""

    name: str
    identity: str
    start_line: int
    end_line: int
    wmc: int
    details: dict


@dataclass
class ExternalResults:
    """Results from analyzers other than lizard; None means the analyzer did not run."""

    duplicates: list[DuplicatePair] | None = None
    god_classes: list[GodClass] | None = None


GOD_CLASS_WMC = 47  # PMD GodClass "very high" WMC limit (Lanza & Marinescu)


class Detector:
    """Runs all detectors for one file with resolved thresholds."""

    def __init__(self, measured: Measured, thresholds: dict[str, float], external: ExternalResults | None = None):
        self.parsed = measured.parsed
        self.metrics = measured.metrics
        self.t = thresholds
        self.language = measured.language
        self.external = external or ExternalResults()

    def detect(self) -> list[Finding]:
        findings: list[Finding] = []
        brain_methods: set[str] = set()
        for fm in self.metrics.functions:
            found = self.function_findings(fm)
            if any(f.smell == BRAIN_METHOD for f in found):
                brain_methods.add(fm.identity)
            findings.extend(found)
        findings.extend(self.file_findings(brain_methods))
        return findings

    # ----- helpers -------------------------------------------------------------
    def _over(self, name: str, value: float) -> bool:
        return th.exceeds(name, value, self.t[name])

    def _sev(self, name: str, value: float) -> float:
        alert = th.ALERT_TIER.get(name)
        return severity(value, self.t[name], self.t.get(alert) if alert else None)

    def _function_finding(self, smell: str, fm: FunctionMetrics, measured: tuple[str, float], message: str) -> Finding:
        name, value = measured
        return Finding(
            smell=smell,
            level="function",
            function=fm.name,
            identity=fm.identity,
            start_line=fm.start_line,
            end_line=fm.end_line,
            value=value,
            threshold=self.t[name],
            severity=self._sev(name, value),
            message=message,
            hint=HINTS[smell],
            details={"cognitive_complexity": fm.cognitive_complexity},
        )

    # ----- function level ------------------------------------------------------
    def function_findings(self, fm: FunctionMetrics) -> list[Finding]:
        checks = (
            self._brain_method,
            self._complex_method,
            self._large_method,
            self._deep_nesting,
            self._bumpy_road,
            self._complex_conditional,
            self._arguments,
        )
        found: list[Finding] = []
        for check in checks:
            finding = check(fm, found)
            if finding is not None:
                found.append(finding)
        return found

    def _is_brain_method(self, fm: FunctionMetrics) -> bool:
        return fm.nesting_depth is not None and (
            self._over("function_lines_of_code_warning", fm.lines_of_code)
            and self._over("function_cyclomatic_complexity_warning", fm.cyclomatic_complexity)
            and self._over("function_nesting_depth_warning", fm.nesting_depth)
        )

    def _brain_method(self, fm: FunctionMetrics, found: list[Finding]) -> Finding | None:
        if not self._is_brain_method(fm):
            return None
        message = (
            f"Large, complex and deeply nested: {fm.lines_of_code} lines, "
            f"cc {fm.cyclomatic_complexity}, nesting {fm.nesting_depth}."
        )
        measured = ("function_cyclomatic_complexity_warning", fm.cyclomatic_complexity)
        finding = self._function_finding(BRAIN_METHOD, fm, measured, message)
        finding.details.update({"lines_of_code": fm.lines_of_code, "nesting_depth": fm.nesting_depth})
        finding.severity = 1.0
        return finding

    def _complex_method(self, fm: FunctionMetrics, found: list[Finding]) -> Finding | None:
        # Brain Method absorbs Complex Method (inferred from public example output).
        name = "function_cyclomatic_complexity_warning"
        if any(f.smell == BRAIN_METHOD for f in found) or not self._over(name, fm.cyclomatic_complexity):
            return None
        cc = fm.cyclomatic_complexity
        return self._function_finding(COMPLEX_METHOD, fm, (name, cc), f"Cyclomatic complexity is {cc}.")

    def _large_method(self, fm: FunctionMetrics, found: list[Finding]) -> Finding | None:
        name = "function_lines_of_code_warning"
        if not self._over(name, fm.lines_of_code):
            return None
        loc = fm.lines_of_code
        return self._function_finding(LARGE_METHOD, fm, (name, loc), f"{loc} lines of code.")

    def _deep_nesting(self, fm: FunctionMetrics, found: list[Finding]) -> Finding | None:
        name = "function_nesting_depth_warning"
        if fm.nesting_depth is None or not self._over(name, fm.nesting_depth):
            return None
        depth = fm.nesting_depth
        return self._function_finding(DEEP_NESTING, fm, (name, depth), f"Control structures nest {depth} levels deep.")

    def _bumpy_road(self, fm: FunctionMetrics, found: list[Finding]) -> Finding | None:
        name = "function_bumpy_road_bumps_for_warning"
        if fm.bumps is None or not self._over(name, len(fm.bumps)):
            return None
        message = f"{len(fm.bumps)} separate chunks of nested logic (depths {fm.bumps})."
        finding = self._function_finding(BUMPY_ROAD, fm, (name, len(fm.bumps)), message)
        finding.details["bump_depths"] = fm.bumps
        return finding

    def _complex_conditional(self, fm: FunctionMetrics, found: list[Finding]) -> Finding | None:
        if not fm.complex_conditionals:
            return None
        name = "function_complex_conditional_branches_warning"
        worst = max(ops for _, ops in fm.complex_conditionals)
        count = len(fm.complex_conditionals)
        message = f"{count} condition(s) with {self.t[name]:g}+ logical operators; the worst has {worst}."
        finding = self._function_finding(COMPLEX_CONDITIONAL, fm, (name, worst), message)
        finding.details.update(
            {"count": count, "conditions": [{"line": line, "operators": ops} for line, ops in fm.complex_conditionals]}
        )
        return finding

    def _arguments(self, fm: FunctionMetrics, found: list[Finding]) -> Finding | None:
        is_ctor = fm.is_constructor
        smell = CONSTRUCTOR_OVER_INJECTION if is_ctor else EXCESS_ARGUMENTS
        name = "constructor_max_arguments" if is_ctor else "function_max_arguments"
        if fm.is_override and not is_ctor:
            return None  # the supertype's declaration owns the signature
        if not self._over(name, fm.arguments):
            return None
        return self._function_finding(smell, fm, (name, fm.arguments), f"{fm.arguments} arguments.")

    # ----- file level ----------------------------------------------------------
    def file_findings(self, brain_methods: set[str]) -> list[Finding]:
        found = [f for f in (self._file_loc(), self._function_count(), self._overall_complexity()) if f]
        found += self._low_cohesion()
        found += self._brain_classes(brain_methods)
        found += self._duplication()
        return found

    def _file_finding(self, smell: str, measured: tuple[str, float], message: str, where: dict | None = None) -> Finding:
        name, value = measured
        where = where or {}
        return Finding(
            smell=smell,
            level="file",
            function=where.get("function"),
            start_line=where.get("start_line"),
            end_line=where.get("end_line"),
            value=value,
            threshold=self.t[name],
            severity=self._sev(name, value),
            message=message,
            hint=HINTS[smell],
            details=where.get("details", {}),
            identity=where.get("identity"),
        )

    def _file_loc(self) -> Finding | None:
        name, loc = "file_lines_of_code_for_warning", self.metrics.lines_of_code
        if not self._over(name, loc):
            return None
        return self._file_finding(FILE_LOC, (name, loc), f"The file has {loc} lines of code.")

    def _function_count(self) -> Finding | None:
        name, count = "file_function_count_warning", self.metrics.function_count
        if not self._over(name, count):
            return None
        return self._file_finding(FUNCTION_COUNT, (name, count), f"The file defines {count} functions.")

    def _overall_complexity(self) -> Finding | None:
        name, mean = "file_mean_cyclomatic_complexity_warning", self.metrics.mean_cyclomatic_complexity
        if not self.metrics.function_count or not self._over(name, mean):
            return None
        return self._file_finding(OVERALL_COMPLEXITY, (name, mean), f"Mean cyclomatic complexity per function is {mean}.")

    @property
    def _classes(self) -> list[ClassInfo]:
        return self.parsed.classes if self.parsed else []

    def _low_cohesion(self) -> list[Finding]:
        found = []
        for cls in self._classes:
            lcom4 = self._cohesion_value(cls)
            if lcom4 is not None:
                message = f"Class {cls.name} has {lcom4} unrelated groups of methods (LCOM4 = {lcom4})."
                found.append(self._file_finding(LOW_COHESION, ("class_lcom4_warning", lcom4), message, _class_where(cls)))
        return found

    def _cohesion_value(self, cls: ClassInfo) -> int | None:
        """The class's LCOM4 when it is checked (enough stateful methods) and over the threshold."""
        measured = self.metrics.cohesion.get(cls.identity)
        if measured is None or measured.methods < self.t["class_lcom4_min_methods"]:
            return None
        return measured.lcom4 if self._over("class_lcom4_warning", measured.lcom4) else None

    def _brain_classes(self, brain_methods: set[str]) -> list[Finding]:
        if self.language == "java":  # PMD GodClass is the Brain Class provider for Java
            return [self._god_class(g) for g in self.external.god_classes or []]
        found = _present(self._brain_class(cls, brain_methods) for cls in self._classes)
        return found or _present([self._brain_module(brain_methods)])

    def _brain_class(self, cls: ClassInfo, brain_methods: set[str]) -> Finding | None:
        if not any(m.identity in brain_methods for m in cls.methods):
            return None
        method_ids = {m.identity for m in cls.methods}
        loc = sum(fm.lines_of_code for fm in self.metrics.functions if fm.identity in method_ids)
        return self._brain_finding(cls.name, (loc, len(cls.methods)), _class_where(cls))

    def _god_class(self, god: GodClass) -> Finding:
        message = f"Class {god.name} is a God Class (PMD): WMC {god.wmc}, ATFD {god.details.get('atfd')}, TCC {god.details.get('tcc_percent')}%."
        return Finding(
            smell=BRAIN_CLASS,
            level="file",
            function=god.name,
            identity=god.identity,
            start_line=god.start_line,
            end_line=god.end_line,
            value=god.wmc,
            threshold=GOD_CLASS_WMC,
            severity=severity(god.wmc, GOD_CLASS_WMC),
            message=message,
            hint=HINTS[BRAIN_CLASS],
            details={"provider": "pmd:GodClass", **god.details},
        )

    def _brain_module(self, brain_methods: set[str]) -> Finding | None:
        if not brain_methods:
            return None
        size = (self.metrics.lines_of_code, self.metrics.function_count)
        return self._brain_finding("module", size, {"function": "<module>"})

    def _brain_finding(self, label: str, size: tuple[int, int], where: dict) -> Finding | None:
        loc, functions = size
        if not (self._over("brain_class_lines_of_code", loc) and self._over("brain_class_function_count", functions)):
            return None
        message = f"The {label} has {loc} lines, {functions} functions and at least one Brain Method."
        finding = self._file_finding(BRAIN_CLASS, ("brain_class_lines_of_code", loc), message, where)
        finding.details = {"functions": functions}
        return finding

    def _duplication(self) -> list[Finding]:
        name = "function_duplication_min_similarity_percentage"
        found = []
        for pair in self.external.duplicates or []:
            percent = round(pair.similarity * 100, 1)
            label = f"{pair.first.name} / {pair.second.name}"
            message = f"{pair.first.name} and {pair.second.name} share a {pair.lines}-line copy ({percent}% of the larger)."
            where = {
                "function": label,
                "start_line": pair.first.start_line,
                "end_line": pair.second.end_line,
                "details": {"other_start_line": pair.second.start_line, "tokens": pair.tokens, "provider": pair.provider},
                "identity": f"{pair.first.identity} / {pair.second.identity}",
            }
            found.append(self._file_finding(DUPLICATION, (name, percent), message, where))
        return found


def _present(findings: Iterable[Finding | None]) -> list[Finding]:
    return [f for f in findings if f is not None]


def _class_where(cls: ClassInfo) -> dict:
    return {
        "function": cls.qualified_name,
        "identity": cls.identity,
        "start_line": cls.start_line,
        "end_line": cls.end_line,
    }



def detect(measured: Measured, thresholds: dict[str, float], external: ExternalResults | None = None) -> list[Finding]:
    return Detector(measured, thresholds, external).detect()
