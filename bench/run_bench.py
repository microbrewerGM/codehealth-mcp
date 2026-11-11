"""Score the human-rated dataset with codehealth and report UC1/UC2/AUC.

Protocol (Borg, Ezzouhri, Tornhill, ICSME 2024): maintainable = human
``Overall`` <= 1; predict maintainable when score >= 9. The dataset's
published reference score (Ghost Echoes, Borg et al. 2024; CSV column
``Code_Health``) is reported as a comparison baseline only; nothing is
fitted to it.

Data: ``$CODEHEALTH_BENCH_DATA`` (see bench/README.md).

All files are reviewed in one batch (one PMD process per tool), and the
per-file findings are cached in ``bench/.cache/findings.json`` so that
``bench.ablate`` and ``bench.calibrate --cached`` can rescore without
re-parsing.

Usage: CODEHEALTH_BENCH_DATA=/path/to/data uv run python -m bench.run_bench [--no-write]
Rewrites bench/results.md and bench/results.json (aggregate metrics only) and
writes per-file rows to bench/.cache/per_file.json (not committed).
"""

from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from codehealth import analysis
from codehealth import score as score_mod

from . import dataset as ds
from . import metrics as m
from .report import BenchRun, render_markdown

HERE = Path(__file__).resolve().parent
REVISIONS = HERE / "revisions.json"
RESULTS_MD = HERE / "results.md"
RESULTS_JSON = HERE / "results.json"
CACHE_JSON = HERE / ".cache" / "findings.json"
# Per-file rows (human labels, reference scores) stay local: the dataset is CC BY 4.0 and
# committed results carry aggregate metrics only.
PER_FILE_JSON = HERE / ".cache" / "per_file.json"
THRESHOLD = m.THRESHOLD
LOC_BASELINE = 275
HUMAN_DIMENSIONS = ("Overall", "Readability", "Understandability", "Complexity_inv", "Modularization_inv")


@dataclass
class Scored:
    row: ds.Row
    repo_path: str
    code_loc: int
    score: float
    findings: list[dict] = field(default_factory=list)  # smell, level, function, key, severity, weight
    size: float = 0.0  # codehealth.score.size_units times the file LoC rule weight

    @property
    def smells(self) -> set[str]:
        return {f["smell"] for f in self.findings}

    def to_dict(self) -> dict:
        return {"row": asdict(self.row), "repo_path": self.repo_path, "code_loc": self.code_loc,
                "score": self.score, "findings": self.findings, "size": self.size}

    @classmethod
    def from_dict(cls, data: dict) -> Scored:
        return cls(ds.Row(**data["row"]), data["repo_path"], data["code_loc"], data["score"], data["findings"],
                   data.get("size", 0.0))


@dataclass(frozen=True)
class Pending:
    """A dataset row matched to a file at the project's revision."""

    row: ds.Row
    repo_path: str
    source: str


def finding_record(f) -> dict:
    return {"smell": f.smell, "level": f.level, "function": f.function, "key": score_mod.penalty_key(f),
            "severity": f.severity, "weight": f.weight}


@dataclass(frozen=True)
class Dataset:
    """The human-rated rows, the local clones and the chosen revision per project."""

    rows: list[ds.Row]
    sources: Path
    revisions: dict

    @classmethod
    def load(cls, csv_path: Path | None = None, sources: Path | None = None) -> Dataset:
        rows = ds.load_rows(csv_path or ds.default_csv())
        return cls(rows, sources or ds.default_sources(), json.loads(REVISIONS.read_text())["projects"])

    def excluded(self) -> dict:
        return {p: {"rows": sum(r.project == p for r in self.rows), "reason": why}
                for p, why in ds.EXCLUDED_PROJECTS.items()}

    def match(self, project: str) -> tuple[list[Pending], dict]:
        """Rows of ``project`` found at its revision, and the match summary."""
        prows = [r for r in self.rows if r.project == project]
        rev = self.revisions[project]
        matched = ds.match_rows(self.sources / project, rev["commit"], prows)
        missing = [r.package_and_class for i, r in enumerate(prows) if i not in matched]
        summary = {"label": rev["label"], "commit": rev["commit"], "date": rev["date"], "repo": rev["repo"],
                   **ds.loc_agreement(prows, matched), "missing_classes": missing}
        return [Pending(prows[i], path, source) for i, (path, source) in sorted(matched.items())], summary


def _score_all(pending: list[Pending], errors: list[dict]) -> list[Scored]:
    """Review every matched file in one batch; files that cannot be reviewed go to ``errors``."""
    reviews = analysis.review_sources([analysis.ReviewRequest(p.source, Path(p.repo_path)) for p in pending])
    scored = []
    for item, review in zip(pending, reviews):
        if isinstance(review, ValueError):
            errors.append({"class": item.row.package_and_class, "error": repr(review)})
        else:
            records = [finding_record(f) for f in review.findings]
            scored.append(Scored(item.row, item.repo_path, ds.code_loc(item.source), review.score, records, review.size))
    return scored


def collect(csv_path: Path | None = None, sources: Path | None = None) -> tuple[list[Scored], dict]:
    """Match and score every row in one review batch; returns scored files and a match summary."""
    data = Dataset.load(csv_path, sources)
    summary: dict = {"projects": {}, "errors": [], "excluded": data.excluded()}
    pending: list[Pending] = []
    for project in ds.REPOS:
        found, summary["projects"][project] = data.match(project)
        pending += found
    return _score_all(pending, summary["errors"]), summary


def save_cache(scored: list[Scored]) -> None:
    CACHE_JSON.parent.mkdir(parents=True, exist_ok=True)
    CACHE_JSON.write_text(json.dumps([s.to_dict() for s in scored]) + "\n")


def load_cache() -> list[Scored]:
    if not CACHE_JSON.is_file():
        raise SystemExit(f"no cached findings at {CACHE_JSON}; run `uv run python -m bench.run_bench` first")
    return [Scored.from_dict(d) for d in json.loads(CACHE_JSON.read_text())]


def _baselines(scored: list[Scored]) -> dict:
    loc_rows = [s for s in scored if s.row.loc is not None]
    loc_maint = [s.row.maintainable for s in loc_rows]
    loc_neg = [-s.row.loc for s in loc_rows]  # higher is better, threshold -275 == loc <= 275
    return {
        "baseline_reference_ge_9": m.evaluate([s.row.maintainable for s in scored],
                                                 [s.row.reference_score for s in scored], THRESHOLD),
        "baseline_loc_le_275": {**m.evaluate(loc_maint, loc_neg, -LOC_BASELINE), "n": len(loc_rows)},
    }


def _per_project(scored: list[Scored]) -> dict:
    result = {}
    for project in ds.REPOS:
        sub = [s for s in scored if s.row.project == project]
        if sub:
            maint = [s.row.maintainable for s in sub]
            result[project] = {"n": len(sub), "maintainable": sum(maint),
                               "ours": m.evaluate(maint, [s.score for s in sub], THRESHOLD),
                               "reference": m.evaluate(maint, [s.row.reference_score for s in sub], THRESHOLD)}
    return result


def evaluate(scored: list[Scored]) -> dict:
    maint = [s.row.maintainable for s in scored]
    ours = [s.score for s in scored]
    ref = [s.row.reference_score for s in scored]
    return {
        "n": len(scored),
        "maintainable": sum(maint),
        "ours": m.evaluate(maint, ours, THRESHOLD),
        **_baselines(scored),
        "spearman_vs_reference": m.spearman(ours, ref),
        "spearman_vs_human": {d: m.spearman(ours, [float(s.row.raw[d]) for s in scored]) for d in HUMAN_DIMENSIONS},
        "spearman_reference_vs_human_overall": m.spearman(ref, [float(s.row.overall) for s in scored]),
        "per_project": _per_project(scored),
    }


def _rate(count: int, total: int) -> float:
    return count / total if total else 0.0


def _penalties(scored: list[Scored]) -> Counter:
    penalty: Counter = Counter()
    for s in scored:
        for f in s.findings:
            penalty[f["smell"]] += score_mod.SMELL_IMPACT.get(f["smell"], 1.0) * f["severity"] * f["weight"]
    return penalty


@dataclass(frozen=True)
class _Firing:
    """Files per class (maintainable or not) and how many of them each smell fires on."""

    total: int
    counts: Counter

    @classmethod
    def of(cls, files: list[Scored]) -> _Firing:
        return cls(len(files), Counter(smell for s in files for smell in s.smells))

    def rate(self, smell: str) -> float:
        return _rate(self.counts[smell], self.total)


def smell_table(scored: list[Scored]) -> list[dict]:
    """How often each smell fires on maintainable vs non-maintainable files."""
    good = _Firing.of([s for s in scored if s.row.maintainable])
    bad = _Firing.of([s for s in scored if not s.row.maintainable])
    penalty = _penalties(scored)
    table = []
    for smell in sorted(set(good.counts) | set(bad.counts) | set(score_mod.SMELL_IMPACT)):
        pg, pb = good.rate(smell), bad.rate(smell)
        table.append({"smell": smell, "maintainable_files": good.counts[smell], "maintainable_rate": pg,
                      "non_maintainable_files": bad.counts[smell], "non_maintainable_rate": pb,
                      "lift": pb / pg if pg else None, "total_penalty": penalty[smell]})
    return sorted(table, key=lambda r: -(r["maintainable_files"] + r["non_maintainable_files"]))


def per_file(scored: list[Scored]) -> list[dict]:
    return [{"project": s.row.project, "class": s.row.package_and_class, "repo_path": s.repo_path,
             "overall": s.row.overall, "maintainable": s.row.maintainable, "score": s.score,
             "reference_score": s.row.reference_score, "dataset_loc": s.row.loc, "code_loc": s.code_loc,
             "smells": sorted(Counter(f["smell"] for f in s.findings).items())} for s in scored]


def write_results(md: str, report: dict) -> None:
    header = ("# Benchmark results\n\nCurrent results, rewritten by `bench/run_bench.py` "
              "(`bench.ablate` and `bench.calibrate` append their sections for the same run).\n\n")
    RESULTS_MD.write_text(header + md + "\n")
    per_file_rows = report.pop("files", [])
    RESULTS_JSON.write_text(json.dumps(report, indent=2, default=str) + "\n")
    PER_FILE_JSON.parent.mkdir(parents=True, exist_ok=True)
    PER_FILE_JSON.write_text(json.dumps(per_file_rows, indent=2, default=str) + "\n")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--csv", type=Path, default=None)
    ap.add_argument("--sources", type=Path, default=None)
    ap.add_argument("--no-write", action="store_true", help="print only; do not touch results files")
    args = ap.parse_args(argv)
    started = time.monotonic()
    scored, summary = collect(args.csv, args.sources)
    summary["runtime_seconds"] = round(time.monotonic() - started, 1)
    save_cache(scored)
    ev, smells = evaluate(scored), smell_table(scored)
    stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    md = render_markdown(BenchRun(stamp, summary, ev, smells, scored))
    print(md)
    if not args.no_write:
        constants = {"K": score_mod.K, "FUNCTION_PENALTY_CAP": score_mod.FUNCTION_PENALTY_CAP,
                     "FILE_SIZE_WEIGHT": score_mod.FILE_SIZE_WEIGHT, "SMELL_IMPACT": score_mod.SMELL_IMPACT}
        write_results(md, {"timestamp": stamp, "constants": constants, "sources": summary, "metrics": ev,
                           "smells": smells, "files": per_file(scored)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
