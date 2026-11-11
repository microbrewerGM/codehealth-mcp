"""Choose, per project, the repo revision that best matches the dataset.

Candidates: every tag plus the last first-parent commit of each month on the
default branch, dated no later than the dataset publication (2020-09-28).
Ranked by (rows found, LoC within 10%, exact LoC); ties go to the latest
date (closest to the dataset). Writes bench/revisions.json.

Usage: uv run python -m bench.select_revisions [--sources DIR] [--csv FILE]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from . import dataset as ds

CUTOFF = "2020-09-28"
OUT = Path(__file__).resolve().parent / "revisions.json"


def candidates(repo: Path) -> list[tuple[str, str, str]]:
    """(label, sha, iso date) for tags and month-end commits up to CUTOFF."""
    seen: dict[str, tuple[str, str, str]] = {}
    for label, sha, date in _tags(repo) + _month_ends(repo):
        seen.setdefault(sha, (label, sha, date))
    return sorted(seen.values(), key=lambda c: c[2])


def _tags(repo: Path) -> list[tuple[str, str, str]]:
    found = []
    for label in ds.git(repo, "tag").split():
        sha, date = ds.git(repo, "show", "-s", "--format=%H %cs", f"{label}^{{commit}}").split()
        found.append((label, sha, date))
    return [c for c in found if c[2] <= CUTOFF]


def _month_ends(repo: Path) -> list[tuple[str, str, str]]:
    """The newest first-parent commit of each month (log is newest first)."""
    months: dict[str, tuple[str, str]] = {}
    for line in ds.git(repo, "log", "--first-parent", "--format=%H %cs", "HEAD").splitlines():
        sha, date = line.split()
        if date <= CUTOFF:
            months.setdefault(date[:7], (sha, date))
    return [(f"month-{month}", sha, date) for month, (sha, date) in months.items()]


def scan(project: str, repo: Path, rows: list[ds.Row]) -> list[dict]:
    results = []
    for label, sha, date in candidates(repo):
        matched = ds.match_rows(repo, sha, rows)
        if not matched:
            continue
        results.append({"label": label, "commit": sha, "date": date, **ds.loc_agreement(rows, matched)})
    results.sort(key=lambda r: (r["found"], r["loc_within_10pct"], r["loc_exact"], r["date"]), reverse=True)
    return results


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--csv", type=Path, default=None)
    ap.add_argument("--sources", type=Path, default=None)
    args = ap.parse_args(argv)
    rows = ds.load_rows(args.csv or ds.default_csv())
    sources = args.sources or ds.default_sources()
    out = {
        "cutoff": CUTOFF,
        "loc_column": ds.LOC_COLUMN,
        "projects": {project: _best_revision(project, slug, sources, rows) for project, slug in ds.REPOS.items()},
        "excluded": _excluded(rows),
    }
    OUT.write_text(json.dumps(out, indent=2) + "\n")
    return 0


def _excluded(rows: list[ds.Row]) -> dict:
    return {
        project: {"rows": sum(r.project == project for r in rows), "reason": reason}
        for project, reason in ds.EXCLUDED_PROJECTS.items()
    }


def _best_revision(project: str, slug: str, sources: Path, rows: list[ds.Row]) -> dict:
    ranked = scan(project, sources / project, [r for r in rows if r.project == project])
    best = ranked[0]
    print(f"{project}: {best['label']} {best['commit'][:10]} {best['date']} found {best['found']}/{best['rows']} "
          f"within10% {best['loc_within_10pct']} exact {best['loc_exact']} ({len(ranked)} candidates)")
    return {"repo": f"https://github.com/{slug}", **best, "top_candidates": ranked[:5]}


if __name__ == "__main__":
    raise SystemExit(main())
