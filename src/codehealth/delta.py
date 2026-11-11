"""Compare two versions of a file and of whole change sets.

Findings are matched by (smell, function identity). Repository access goes
through :mod:`codehealth.gitrepo`, which never lets git read the working
tree (so repository-local filters and hooks cannot run).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import config, gitrepo
from .analysis import FileReview, ReviewRequest, cross_file_duplication, review_sources
from .gitrepo import GitError, check_ref  # noqa: F401  (public re-exports)
from .lang import is_supported, language_for
from .smells import Finding

IMPROVED = "improved"
DEGRADED = "degraded"
STABLE = "stable"
UNKNOWN = "unknown"
REMOVED = "removed"
GATE_OK = frozenset({STABLE, IMPROVED})


@dataclass
class FileDelta:
    path: str
    verdict: str
    old_score: float | None
    new_score: float | None
    new_findings: list[Finding] = field(default_factory=list)
    worsened: list[dict] = field(default_factory=list)
    improved: list[dict] = field(default_factory=list)
    fixed: list[Finding] = field(default_factory=list)
    error: str | None = None
    # Smell-only scores (no file-size term): growing a file is not a regression by itself.
    smell_change: float = 0.0

    @property
    def gate_passed(self) -> bool:
        """Removed files never block the gate; everything else must be stable or improved."""
        return self.verdict == REMOVED or self.verdict in GATE_OK

    def to_dict(self) -> dict:
        data = {
            "path": self.path,
            "verdict": self.verdict,
            "old_score": self.old_score,
            "new_score": self.new_score,
            "new_findings": [f.to_dict() for f in self.new_findings],
            "worsened": self.worsened,
            "improved": self.improved,
            "fixed": [{"smell": f.smell, "function": f.function} for f in self.fixed],
        }
        if self.error:
            data["error"] = self.error
        return {k: v for k, v in data.items() if v not in ([], None)}


# ----- pure comparison -------------------------------------------------------
def _score(review: FileReview | None) -> float | None:
    return review.score if review else None


def _by_key(review: FileReview | None) -> dict:
    return {f.key: f for f in review.findings} if review else {}


def compare_reviews(path: str, old: FileReview | None, new: FileReview | None) -> FileDelta:
    if new is None:
        return FileDelta(path, REMOVED, _score(old), None)
    delta = FileDelta(path, STABLE, _score(old), _score(new))
    if old is not None:
        delta.smell_change = new.smell_score - old.smell_score
    _diff_findings(delta, _by_key(old), _by_key(new))
    delta.verdict = _verdict(delta)
    return delta


def _diff_findings(delta: FileDelta, old_findings: dict, new_findings: dict) -> None:
    for key, finding in new_findings.items():
        before = old_findings.get(key)
        if before is None:
            delta.new_findings.append(finding)
        elif finding.value != before.value:
            change = {"smell": finding.smell, "function": finding.function, "old": before.value, "new": finding.value}
            (delta.worsened if finding.value > before.value else delta.improved).append(change)
    delta.fixed = [f for key, f in old_findings.items() if key not in new_findings]


def _verdict(delta: FileDelta) -> str:
    if _got_worse(delta):
        return DEGRADED
    if _got_better(delta):
        return IMPROVED
    return STABLE


def _got_worse(delta: FileDelta) -> bool:
    return delta.smell_change < 0 or bool(delta.new_findings or delta.worsened)


def _got_better(delta: FileDelta) -> bool:
    return delta.smell_change > 0 or bool(delta.fixed or delta.improved)


@dataclass(frozen=True)
class Change:
    """Two versions of one file (None when absent) and the rules for both."""

    path: Path
    old_text: str | None
    new_text: str | None
    rules: config.Rules | None = None


def compare_changes(changes: list[Change]) -> list[FileDelta]:
    """Review every old and new version in one batch (one PMD run per tool), then diff."""
    requests: list[ReviewRequest] = []
    slots: list[tuple[int | None, int | None]] = []
    for c in changes:
        slots.append((_enqueue(requests, c, c.old_text), _enqueue(requests, c, c.new_text)))
    reviews = review_sources(requests)
    return [_delta_for(c, reviews, slot) for c, slot in zip(changes, slots)]


def _enqueue(requests: list[ReviewRequest], change: Change, text: str | None) -> int | None:
    if text is None:
        return None
    requests.append(ReviewRequest(text, change.path, change.rules))
    return len(requests) - 1


def _delta_for(change: Change, reviews: list, slot: tuple[int | None, int | None]) -> FileDelta:
    old, new = (reviews[i] if i is not None else None for i in slot)
    error = next((r for r in (old, new) if isinstance(r, ValueError)), None)
    if error is not None:
        return FileDelta(str(change.path), UNKNOWN, None, None, error=str(error))
    return compare_reviews(str(change.path), old, new)


def compare_sources(path: Path, old_text: str | None, new_text: str | None, rules: config.Rules | None = None) -> FileDelta:
    return compare_changes([Change(path, old_text, new_text, rules)])[0]


# ----- rules from git ---------------------------------------------------------------
@dataclass
class RulesSnapshot:
    """Rules file content at one revision (root-level rules files only)."""

    path: str | None = None
    raw: bytes | None = None
    data: dict | None = None

    def rules(self, relpath: str) -> config.Rules | None:
        language = language_for(relpath)
        return config.rules_from_data(self.data, relpath, language, self.path) if language else None


def _rules_paths() -> list[str]:
    return [p.as_posix() for p in config.CONFIG_PATHS]


def rules_at(repo: Path, entries: dict[str, str], label: str) -> RulesSnapshot:
    for relpath in _rules_paths():
        if relpath in entries:
            raw = gitrepo.read_blob(repo, entries[relpath])
            return _snapshot(relpath, raw, f"{label}:{relpath}")
    return RulesSnapshot()


def rules_in_worktree(repo: Path) -> RulesSnapshot:
    for relpath in _rules_paths():
        raw = gitrepo.read_worktree(repo, relpath)
        if raw is not None:
            return _snapshot(relpath, raw, relpath)
    return RulesSnapshot()


def _snapshot(relpath: str, raw: bytes, source: str) -> RulesSnapshot:
    data = config.parse_config(raw.decode("utf-8", errors="replace"), source)
    return RulesSnapshot(relpath, raw, data)


def rules_diff(base: RulesSnapshot, other: RulesSnapshot) -> list[dict]:
    """Entries whose weight/value differ between two rules files."""
    old, new = _flatten(base.data), _flatten(other.data)
    return [
        {"matching_content_path": k[0], "kind": k[1], "name": k[2], "old": old.get(k), "new": new.get(k)}
        for k in sorted(old.keys() | new.keys())
        if old.get(k) != new.get(k)
    ]


def _flatten(data: dict | None) -> dict[tuple[str, str, str], float]:
    flat: dict[tuple[str, str, str], float] = {}
    for rule_set in (data or {}).get("rule_sets", []):
        pattern = rule_set.get("matching_content_path", config.DEFAULT_PATTERN)
        for kind, key in (("rules", "weight"), ("thresholds", "value")):
            for entry in rule_set.get(kind, []):
                flat.setdefault((pattern, kind, entry["name"]), entry[key])
    return flat


def _rules_warning(summary: dict, base: RulesSnapshot, other: RulesSnapshot) -> None:
    if base.raw != other.raw:
        summary["rules_changed"] = True
        summary["rules_diff"] = rules_diff(base, other)


# ----- repository level -----------------------------------------------------------
def _text(data: bytes | None) -> str | None:
    return data.decode("utf-8", errors="replace") if data is not None else None


def _blob_text(repo: Path, oid: str | None) -> str | None:
    return _text(gitrepo.read_blob(repo, oid)) if oid else None


@dataclass
class _Pending:
    """A changed path: old blob id and new bytes (None when absent)."""

    path: str
    old_oid: str | None
    new_bytes: bytes | None


def _worktree_changes(repo: Path, base: dict[str, str], paths: set[str]) -> list[_Pending]:
    fmt = gitrepo.object_format(repo)
    pending = []
    for path in sorted(p for p in paths if is_supported(p)):
        data = gitrepo.read_worktree(repo, path)
        new_oid = gitrepo.blob_oid(data, fmt) if data is not None else None
        if new_oid != base.get(path):
            pending.append(_Pending(path, base.get(path), data))
    return _pair_renames(pending, fmt)


def _pair_renames(pending: list[_Pending], fmt: str) -> list[_Pending]:
    """Pair a removed path with an added path holding the same content (a pure rename)."""
    removed = {p.old_oid: p for p in pending if p.new_bytes is None}
    for item in filter(_is_added, pending):
        source = removed.pop(gitrepo.blob_oid(item.new_bytes, fmt), None)
        item.old_oid = source.old_oid if source else None
    return [p for p in pending if _not_renamed_away(p, removed)]


def _not_renamed_away(item: _Pending, unpaired_removals: dict) -> bool:
    """Keep present files and removals that no added file took over."""
    return item.new_bytes is not None or item.old_oid in unpaired_removals


def _is_added(item: _Pending) -> bool:
    return item.old_oid is None and item.new_bytes is not None


def pre_commit_safeguard(repo: Path) -> dict:
    """Staged and modified tracked files vs HEAD; untracked files are not included."""
    head = gitrepo.tree_entries(repo, "HEAD") if gitrepo.has_head(repo) else {}
    base_rules = rules_at(repo, head, "HEAD")
    paths = set(head) | set(gitrepo.index_entries(repo))
    changes = _worktree_changes(repo, head, paths)
    deltas = compare_changes(
        [Change(Path(p.path), _blob_text(repo, p.old_oid), _text(p.new_bytes), base_rules.rules(p.path)) for p in changes]
    )
    summary = summarize(deltas)
    _rules_warning(summary, base_rules, rules_in_worktree(repo))
    _cross_file(summary, {p.path: _text(p.new_bytes) for p in changes})
    return summary


def file_delta_against_ref(repo: Path, relpath: str, ref: str = "HEAD") -> FileDelta:
    """Old content from ``ref``, new content from the working tree."""
    entries = gitrepo.tree_entries(repo, ref) if gitrepo.has_head(repo) or ref != "HEAD" else {}
    new = _text(gitrepo.read_worktree(repo, relpath))
    rules = rules_at(repo, entries, ref).rules(relpath)
    return compare_sources(Path(relpath), _blob_text(repo, entries.get(relpath)), new, rules)


@dataclass(frozen=True)
class _TreeDiff:
    """Old tree entries, new file texts, and the rules used for both sides."""

    repo: Path
    old_entries: dict[str, str]
    new_texts: dict[str, str | None]
    rules: RulesSnapshot

    def change(self, c: gitrepo.Change) -> Change:
        path = c.new_path or c.old_path
        old = _blob_text(self.repo, self.old_entries.get(c.old_path or ""))
        return Change(Path(path), old, self.new_texts.get(c.new_path or ""), self.rules.rules(path))


def analyze_change_set(repo: Path, base_ref: str) -> dict:
    """Committed changes on HEAD since its merge base with ``base_ref`` (tree to tree)."""
    base = gitrepo.merge_base(repo, base_ref)
    old_entries, new_entries = gitrepo.tree_entries(repo, base), gitrepo.tree_entries(repo, "HEAD")
    changes = [c for c in gitrepo.tree_changes(repo, base, "HEAD") if is_supported(c.new_path or c.old_path)]
    new_texts = {c.new_path: _blob_text(repo, new_entries.get(c.new_path)) for c in changes if c.new_path}
    diff = _TreeDiff(repo, old_entries, new_texts, rules_at(repo, old_entries, base))
    summary = summarize(compare_changes([diff.change(c) for c in changes]))
    summary["merge_base"] = base
    _rules_warning(summary, diff.rules, rules_at(repo, new_entries, "HEAD"))
    _cross_file(summary, new_texts)
    return summary


def _cross_file(summary: dict, texts: dict[str, str | None]) -> None:
    """Informational duplication between changed files: CPD plus renamed clones (does not affect the gate)."""
    present = {path: text for path, text in texts.items() if text is not None}
    if len(present) < 2:
        return
    result = cross_file_duplication(present)
    summary["analyzers"] = {"cross_file_cpd": result["analyzer"], "cross_file_renamed_clones": result["renamed_clones"]}
    if result["duplicates"]:
        summary["cross_file_duplication"] = result["duplicates"]


def repo_root(path: Path) -> Path:
    return gitrepo.repo_root(path)


def summarize(deltas: list[FileDelta]) -> dict:
    counts = {v: 0 for v in (IMPROVED, DEGRADED, STABLE, UNKNOWN, REMOVED)}
    for d in deltas:
        counts[d.verdict] += 1
    return {
        "quality_gate": "passed" if all(d.gate_passed for d in deltas) else "failed",
        "counts": {k: v for k, v in counts.items() if v},
        "files": [d.to_dict() for d in deltas],
    }
