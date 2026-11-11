"""PMD enrichment for one or many files with as few JVM starts as possible.

Every file of a batch is copied into one private scratch directory (its own
numbered subdirectory, so equal names never collide). CPD then runs once per
(lexer, minimum token count) group and the Java design rules run once over
all Java files. Results are mapped back to each file by its scratch path;
duplication pairs are kept only when both ends lie in the same file, which is
exactly what a single-file CPD run reports.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import config, lizard_metrics, pmd
from . import smells as s
from .duplication import TOKEN_LANGUAGES, map_duplications
from .lang.base import ParsedFile
from .metrics import Measured
from .smells import DuplicatePair, ExternalResults, GodClass

# Smells measured only by our tree-sitter code (see DESIGN.md, analyzer table).
TREE_SITTER_SMELLS = (s.BUMPY_ROAD, s.COMPLEX_CONDITIONAL, s.LOW_COHESION)
NESTING_SMELLS = (s.DEEP_NESTING, s.BRAIN_METHOD)
DIRECTIVES = "comment directives"


class AnalyzerReport:
    """Which analyzers ran, their versions, and which smells could not be measured."""

    def __init__(self, language: str, parsed: ParsedFile | None):
        self.language = language
        self.unavailable: list[str] = []
        self.unavailable_features: list[str] = []
        self.notes: list[str] = []
        # Renamed clones come from our tree-sitter tokens, with or without PMD.
        self.token_clones = parsed is not None and language in TOKEN_LANGUAGES
        # lizard's ``nd`` pass runs only when tree-sitter does not supply nesting depth.
        extensions = list(lizard_metrics.extensions_used(with_nesting=parsed is None))
        self.data: dict = {
            "lizard": {"ran": True, "version": lizard_metrics.version(), "extensions": extensions},
            "tree_sitter": {"ran": parsed is not None},
        }
        if parsed is None:
            self._without_tree_sitter()

    def _without_tree_sitter(self) -> None:
        self.data["tree_sitter"]["reason"] = f"no tree-sitter adapter for {self.language}"
        self.unavailable += TREE_SITTER_SMELLS
        self.unavailable_features.append(DIRECTIVES)
        self.notes.append("Brain Class is checked at module level only (no class structure without tree-sitter)")
        if not lizard_metrics.nesting_is_reliable(self.language):
            self.unavailable += NESTING_SMELLS

    def pmd_failed(self, data: dict) -> None:
        self.data["pmd"] = data
        if not self.token_clones:
            self.unavailable.append(s.DUPLICATION)
        if self.language == "java":
            self.unavailable.append(s.BRAIN_CLASS)

    def to_dict(self) -> dict:
        data = dict(self.data)
        data["unavailable_smells"] = sorted(set(self.unavailable))
        if self.unavailable_features:
            data["unavailable_features"] = self.unavailable_features
        if self.notes:
            data["notes"] = self.notes
        return data


@dataclass
class PmdResult:
    """What PMD found for one file; ``failed`` discards everything."""

    duplicates: list[DuplicatePair] | None = None
    god_classes: list[GodClass] | None = None
    violations: list[pmd.Violation] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    failed: bool = False

    def external(self) -> ExternalResults:
        if self.failed:
            return ExternalResults()
        return ExternalResults(duplicates=self.duplicates, god_classes=self.god_classes)

    def kept_violations(self) -> list[pmd.Violation]:
        return [] if self.failed else self.violations


@dataclass
class Target:
    """One file of a PMD batch."""

    source: str
    path: Path
    m: Measured
    rules: config.Rules
    report: AnalyzerReport
    result: PmdResult = field(default_factory=PmdResult)

    @property
    def limits(self) -> dict[str, float]:
        return self.rules.thresholds

    @property
    def min_loc(self) -> float:
        return self.limits["function_duplication_min_lines_of_code_for_check"]

    def needs_cpd(self) -> bool:
        """CPD only pays off when two functions are big enough to compare."""
        if self.m.language not in pmd.CPD_LANGUAGES:
            return False
        return sum(1 for f in self.m.metrics.functions if f.lines_of_code >= self.min_loc) >= 2

    def fail(self, data: dict) -> None:
        if not self.result.failed:
            self.result.failed = True
            self.report.pmd_failed(data)


def enrich(targets: list[Target]) -> None:
    """Run CPD and the Java design rules for all ``targets``; record results on each."""
    install, reason = pmd.locate() if targets else (None, None)
    if install is None:
        for t in targets:
            t.report.pmd_failed({"ran": False, "reason": reason})
        return
    for t in targets:
        _prepare(t)
    _run_batch(install, targets)
    for t in (t for t in targets if not t.result.failed):
        t.report.data["pmd"] = {"ran": True, "version": install.version, "tools": t.result.tools}


def _run_batch(install: pmd.PmdInstall, targets: list[Target]) -> None:
    with pmd.scratch_dir() as work:
        batch = _Batch(install, work)
        for key, group in _cpd_groups(targets).items():
            batch.cpd(key, group)
        batch.java_rules([t for t in targets if t.m.language == "java"])


def _prepare(t: Target) -> None:
    if t.m.language in pmd.CPD_LANGUAGES:
        t.result.duplicates = []
    else:
        t.report.unavailable.append(s.DUPLICATION)
        t.report.notes.append(f"CPD has no lexer for {t.m.language}")


def _cpd_groups(targets: list[Target]) -> dict[tuple[str, int], list[Target]]:
    groups: dict[tuple[str, int], list[Target]] = {}
    for t in targets:
        if t.needs_cpd():
            key = (t.m.language, int(t.limits["function_duplication_min_tokens"]))
            groups.setdefault(key, []).append(t)
    return groups


def scratch_name(path: Path) -> str:
    name = Path(path).name
    return name if name not in ("", ".", "..") else f"source{Path(path).suffix}"


class _Batch:
    """One scratch directory; one PMD process per tool run."""

    def __init__(self, install: pmd.PmdInstall, work: Path):
        self.install, self.work = install, work

    def _write(self, label: str, targets: list[Target]) -> tuple[Path, dict[str, Target]]:
        root = self.work / label
        by_path: dict[str, Target] = {}
        for i, t in enumerate(targets):
            copy = root / str(i) / scratch_name(t.path)
            copy.parent.mkdir(parents=True, exist_ok=True)
            copy.write_text(t.source, encoding="utf-8")
            by_path[str(copy.resolve())] = t
        return root, by_path

    def _fail(self, targets: list[Target], exc: Exception) -> None:
        for t in targets:
            t.fail({"ran": False, "version": self.install.version, "reason": str(exc)})

    def cpd(self, key: tuple[str, int], targets: list[Target]) -> None:
        language, min_tokens = key
        root, by_path = self._write(f"cpd-{language}-{min_tokens}", targets)
        try:
            dups = resolve_paths(pmd.run_cpd(self.install, root, language, min_tokens))
        except (pmd.PmdError, OSError) as exc:
            self._fail(targets, exc)
            return
        for path, t in by_path.items():
            similarity = t.limits["function_duplication_min_similarity_percentage"] / 100
            pairs = map_duplications(dups, {path: t.m.metrics.functions}, t.min_loc, similarity)
            t.result.duplicates = [p.pair for p in pairs]
            t.result.tools.append("cpd")

    def java_rules(self, targets: list[Target]) -> None:
        if not targets:
            return
        root, by_path = self._write("java", targets)
        try:
            violations = pmd.run_java_rules(self.install, root)
        except (pmd.PmdError, OSError) as exc:
            self._fail(targets, exc)
            return
        for v in violations:
            owner = by_path.get(str(Path(v.path).resolve()))
            if owner is not None:
                owner.result.violations.append(v)
        for t in targets:
            t.result.god_classes = god_classes(t.result.violations, t.m.parsed)
            t.result.tools.append("check:java-design")


def resolve_paths(dups: list[pmd.Duplication]) -> list[pmd.Duplication]:
    """CPD may print the scratch path through a symlink (e.g. /tmp -> /private/tmp); normalise it."""
    return [
        pmd.Duplication(
            d.lines,
            d.tokens,
            tuple(pmd.Occurrence(str(Path(o.path).resolve()), o.start_line, o.end_line) for o in d.occurrences),
        )
        for d in dups
    ]


def god_classes(violations: list[pmd.Violation], parsed: ParsedFile | None) -> list[GodClass]:
    classes = parsed.classes if parsed else []
    return [_god_class(v, classes) for v in violations if v.rule == "GodClass"]


def _god_class(v: pmd.Violation, classes: list) -> GodClass:
    holders = [c for c in classes if c.start_line <= v.begin_line <= c.end_line]
    metrics = pmd.god_class_metrics(v.message) or {}
    wmc = int(metrics.get("wmc", s.GOD_CLASS_WMC))
    if not holders:
        label = f"<class@{v.begin_line}>"
        return GodClass(label, label, v.begin_line, v.end_line, wmc, metrics)
    cls = max(holders, key=lambda c: c.start_line)
    return GodClass(cls.qualified_name, cls.identity, cls.start_line, cls.end_line, wmc, metrics)
