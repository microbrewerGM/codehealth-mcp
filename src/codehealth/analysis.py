"""Review one file: measure (lizard + tree-sitter), enrich (PMD), detect smells, apply config, score."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import config, lizard_metrics, pmd, score, thresholds
from . import smells as s
from .duplication import TOKEN_LANGUAGES, TOKEN_PROVIDER, Limits, LocatedPair, candidates, map_duplications, merge_pairs, token_pairs
from .enrich import AnalyzerReport, Target, enrich, resolve_paths
from .lang import has_adapter, language_for, parse_source, require_language
from .metrics import Measured, file_metrics
from .smells import Finding, detect


@dataclass
class FileReview:
    path: str
    language: str
    score: float
    findings: list[Finding] = field(default_factory=list)
    lines_of_code: int = 0
    function_count: int = 0
    config_path: str | None = None
    analyzers: dict = field(default_factory=dict)
    pmd_violations: list[dict] = field(default_factory=list)
    size: float = 0.0  # score.size_units times the file LoC rule weight

    @property
    def smell_score(self) -> float:
        """The score without the file-size term (what delta verdicts compare)."""
        return score.code_health(self.findings)

    @property
    def category(self) -> str:
        return score.category(self.score)

    def to_dict(self, include_findings: bool = True) -> dict:
        data = {
            "path": self.path,
            "language": self.language,
            "score": self.score,
            "category": self.category,
            "optimal": score.is_optimal(self.score),
            "lines_of_code": self.lines_of_code,
            "functions": self.function_count,
        }
        if self.size:
            data["file_size_penalty"] = round(score.FILE_SIZE_WEIGHT * self.size, 3)
        if self.config_path:
            data["rules_file"] = self.config_path
        if include_findings:
            data["findings"] = [f.to_dict() for f in self.findings]
            if self.pmd_violations:
                data["pmd_violations"] = self.pmd_violations
        data["analyzers"] = self.analyzers
        return data


class FileTooLargeError(ValueError):
    pass


def check_size(size_bytes: int, line_count: int, limits: dict[str, float]) -> None:
    max_bytes, max_lines = limits["file_max_bytes"], limits["file_max_lines"]
    if size_bytes > max_bytes or line_count > max_lines:
        raise FileTooLargeError(
            f"file too large to analyze: {size_bytes} bytes / {line_count} lines "
            f"(limits {max_bytes:g} bytes / {max_lines:g} lines; raise file_max_bytes or file_max_lines in the rules file)"
        )


# ----- measuring -----------------------------------------------------------------------
def measure_source(source: str, path: Path, limits: dict[str, float]) -> Measured:
    """lizard metrics for every supported language, plus tree-sitter where we have an adapter."""
    language = require_language(path)
    parsed = parse_source(source, path) if has_adapter(language) else None
    lz_file = lizard_metrics.analyze(source, path, language, with_nesting=parsed is None)
    return Measured(language, parsed, file_metrics(lz_file, parsed, limits))


def _attach_violations(findings: list[Finding], violations: list[pmd.Violation]) -> None:
    """PMD rules that are not a catalog smell become details on the matching function findings."""
    for v in violations:
        if v.rule == "GodClass":
            continue
        for finding in findings:
            if finding.level == "function" and finding.start_line <= v.begin_line <= finding.end_line:
                finding.details.setdefault("pmd", []).append(v.to_dict())


# ----- review -------------------------------------------------------------------------------
@dataclass(frozen=True)
class ReviewRequest:
    """``source`` reviewed as if it were the file at ``path`` (which need not exist)."""

    source: str
    path: Path
    rules: config.Rules | None = None


def review_sources(requests: list[ReviewRequest]) -> list[FileReview | ValueError]:
    """Review many sources with one PMD batch; a ValueError takes the place of a file that cannot be reviewed."""
    prepared = [_prepare(r) for r in requests]
    enrich([t for t in prepared if isinstance(t, Target)])
    return [_finish(t) if isinstance(t, Target) else t for t in prepared]


def review_source(source: str, path: Path, rules: config.Rules | None = None) -> FileReview:
    """Review ``source`` as if it were the file at ``path`` (which need not exist)."""
    result = review_sources([ReviewRequest(source, path, rules)])[0]
    if isinstance(result, ValueError):
        raise result
    return result


def _prepare(request: ReviewRequest) -> Target | ValueError:
    path = request.path
    rules = request.rules or config.Rules(thresholds=thresholds.defaults_for(language_for(path) or ""))
    try:
        check_size(len(request.source.encode("utf-8", errors="replace")), request.source.count("\n") + 1, rules.thresholds)
        m = measure_source(request.source, path, rules.thresholds)
    except ValueError as exc:
        return exc
    return Target(request.source, path, m, rules, AnalyzerReport(m.language, m.parsed))


def _finish(t: Target) -> FileReview:
    m, rules = t.m, t.rules
    violations = t.result.kept_violations()
    external = t.result.external()
    external.duplicates = _with_renamed_clones(t, external.duplicates)
    findings = detect(m, rules.thresholds, external)
    _attach_violations(findings, violations)
    disabled = config.disabled_smells(m.parsed) if m.parsed is not None else {}
    findings = _apply_rules(findings, rules, disabled)
    size = score.size_units(m.metrics.lines_of_code, rules.thresholds) * rules.weight(s.FILE_LOC)
    return FileReview(
        path=str(t.path),
        language=m.language,
        score=score.code_health(findings, size),
        size=size,
        findings=findings,
        lines_of_code=m.metrics.lines_of_code,
        function_count=m.metrics.function_count,
        config_path=rules.config_path,
        analyzers=t.report.to_dict(),
        pmd_violations=[v.to_dict() for v in violations],
    )


def _with_renamed_clones(t: Target, cpd: list[s.DuplicatePair] | None) -> list[s.DuplicatePair] | None:
    """CPD pairs plus renamed clones from normalized tokens (languages CPD cannot normalise; works without PMD)."""
    if not t.report.token_clones:
        return cpd
    found = candidates("", t.m.parsed, t.m.metrics.functions, t.min_loc)
    renamed = token_pairs(found, _duplication_limits(t.limits), t.limits["function_duplication_min_tokens"])
    return [p.pair for p in merge_pairs([LocatedPair("", "", pair) for pair in cpd or []], renamed)]


def _apply_rules(findings: list[Finding], rules: config.Rules, disabled: dict[str, set[str]]) -> list[Finding]:
    kept = []
    for finding in findings:
        finding.weight = rules.weight(finding.smell)
        if finding.weight <= 0 or _is_disabled(finding, disabled):
            continue
        kept.append(finding)
    return kept


def _is_disabled(finding: Finding, disabled: dict[str, set[str]]) -> bool:
    if finding.level != "function":
        return False
    smells = disabled.get(finding.function or "", set())
    return config.DISABLE_ALL in smells or finding.smell in smells


def file_request(path: Path) -> ReviewRequest:
    """Read a file on disk with the rules file of its repository (size checked before reading)."""
    language = language_for(path)
    rules = config.rules_for(path, language) if language else None
    if rules is not None:
        check_size(path.stat().st_size, 0, rules.thresholds)  # refuse huge files before reading them
    return ReviewRequest(path.read_text(encoding="utf-8", errors="replace"), path, rules)


def review_files(paths: list[Path]) -> list[FileReview]:
    """Review files on disk in one PMD batch; raises the first file's error, like :func:`review_file`."""
    results = review_sources([file_request(p) for p in paths])
    for result in results:
        if isinstance(result, ValueError):
            raise result
    return results  # type: ignore[return-value]


def review_file(path: Path) -> FileReview:
    """Review a file on disk using the rules file of its repository."""
    return review_files([path])[0]


# ----- cross-file duplication (repository-level tools) -----------------------------------------
def cross_file_duplication(files: dict[str, str]) -> dict:
    """CPD plus renamed clones across ``{relpath: text}``; only pairs in different files are reported.

    Informational: per-file scores are unchanged. Uses default thresholds for
    each file's language (rules files are not consulted here). Renamed clones
    (normalized tree-sitter tokens) are found even when PMD is unavailable.
    """
    groups = [members for members in _cpd_groups(files).values() if len(members) >= 2]
    renamed = [p for members in groups for p in _cross_file_tokens(members)]
    analyzer, copies = _cross_file_cpd(groups, files)
    pairs = [p for p in merge_pairs(copies, renamed) if p.first_path != p.second_path]
    tokens = {"ran": True, "provider": TOKEN_PROVIDER, "languages": sorted(TOKEN_LANGUAGES)}
    return {"analyzer": analyzer, "renamed_clones": tokens, "duplicates": [_cross_entry(p) for p in pairs]}


def _cross_file_cpd(groups: list[dict[str, Measured]], files: dict[str, str]) -> tuple[dict, list[LocatedPair]]:
    """CPD over each lexer group: (analyzer report, copied function pairs)."""
    install, reason = pmd.locate()
    if install is None:
        return {"ran": False, "reason": reason}, []
    try:
        copies = [p for members in groups for p in _cross_file_group(install, members, files)]
    except (pmd.PmdError, OSError) as exc:
        return {"ran": False, "version": install.version, "reason": str(exc)}, []
    return {"ran": True, "version": install.version, "tools": ["cpd"]}, copies


def _cpd_groups(files: dict[str, str]) -> dict[str, dict[str, Measured]]:
    """Files with at least one function big enough to check, grouped by CPD lexer."""
    groups: dict[str, dict[str, Measured]] = {}
    for relpath, text in sorted(files.items()):
        m = _measure_for_cpd(relpath, text)
        if m is not None:
            groups.setdefault(pmd.CPD_LANGUAGES[m.language], {})[relpath] = m
    return groups


def _measure_for_cpd(relpath: str, text: str) -> Measured | None:
    language = language_for(relpath)
    if language not in pmd.CPD_LANGUAGES:
        return None
    limits = thresholds.defaults_for(language)
    try:
        check_size(len(text.encode("utf-8", errors="replace")), text.count("\n") + 1, limits)
        m = measure_source(text, Path(relpath), limits)
    except ValueError:
        return None
    min_loc = limits["function_duplication_min_lines_of_code_for_check"]
    return m if any(f.lines_of_code >= min_loc for f in m.metrics.functions) else None


def _duplication_limits(limits: dict[str, float]) -> Limits:
    return Limits(limits["function_duplication_min_lines_of_code_for_check"], limits["function_duplication_min_similarity_percentage"] / 100)


def _group_limits(members: dict[str, Measured]) -> dict[str, float]:
    return thresholds.defaults_for(next(iter(members.values())).language)


def _cross_file_tokens(members: dict[str, Measured]) -> list[LocatedPair]:
    """Renamed clones between the files of one lexer group (one inverted index over all their functions)."""
    limits = _group_limits(members)
    dup = _duplication_limits(limits)
    found = [c for relpath, m in members.items() for c in candidates(relpath, m.parsed, m.metrics.functions, dup.min_loc)]
    return token_pairs(found, dup, limits["function_duplication_min_tokens"])


def _cross_file_group(install: pmd.PmdInstall, members: dict[str, Measured], files: dict[str, str]) -> list[LocatedPair]:
    limits = _group_limits(members)
    dup = _duplication_limits(limits)
    language = next(iter(members.values())).language
    with pmd.scratch_dir() as work:
        written = pmd.write_sources(work, {relpath: files[relpath] for relpath in members})
        by_path = {str(path): members[relpath].metrics.functions for path, relpath in written.items()}
        dups = resolve_paths(pmd.run_cpd(install, work, language, limits["function_duplication_min_tokens"]))
        pairs = map_duplications(dups, by_path, dup.min_loc, dup.min_similarity)
    rel = {str(path): relpath for path, relpath in written.items()}
    return [LocatedPair(rel[p.first_path], rel[p.second_path], p.pair) for p in pairs]


def _cross_entry(located: LocatedPair) -> dict:
    def side(path: str, fm) -> dict:
        return {"path": path, "function": fm.name, "start_line": fm.start_line, "end_line": fm.end_line}

    pair = located.pair
    return {
        "smell": s.DUPLICATION,
        "first": side(located.first_path, pair.first),
        "second": side(located.second_path, pair.second),
        "similarity": round(pair.similarity * 100, 1),
        "lines": pair.lines,
        "tokens": pair.tokens,
        "provider": pair.provider,
    }
