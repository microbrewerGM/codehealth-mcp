"""Load the Ghost Echoes CSV and map its rows to files in public git repos.

The data lives outside the repository, in ``$CODEHEALTH_BENCH_DATA`` (see
bench/README.md for how to obtain it).

The dataset ships no Java sources we can fetch, so each row's ``path`` is
mapped to a file in the project's public GitHub repo at a chosen revision.

Column note: the CSV header is misaligned with its metric values. ``line`` is
not a file line count (values like 27 for a 900-line class). The paper's
"LoC <= 275" baseline is reproduced exactly (UC2 P 0.87 / R 0.71) by the
column labelled ``nos``, so ``nos`` is used as the dataset's LoC. It tracks
non-comment, non-blank lines (``code_loc``) closely but not exactly.
"""

from __future__ import annotations

import csv
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

# CSV projectname -> local clone directory name and public GitHub repo.
REPOS: dict[str, str] = {
    "argoUML": "argouml-tigris-org/argouml",
    "aoi": "ArtOfIllusion/ArtOfIllusion",
    "jsweet": "cincheo/jsweet",
    "junit4": "junit-team/junit4",
}
EXCLUDED_PROJECTS = {"diarymanagement": "not publicly available"}
LOC_COLUMN = "nos"  # see module docstring
# Published reference score per file from the Ghost Echoes replication package
# (Borg et al. 2024); the CSV names the column ``Code_Health``.
REFERENCE_COLUMN = "Code_Health"


@dataclass(frozen=True)
class Row:
    project: str
    package_and_class: str
    path: str
    overall: int  # 0 best .. 3 worst (human majority)
    reference_score: float  # published reference score (Ghost Echoes, Borg et al. 2024); evaluation only
    loc: float | None  # dataset LoC (``nos`` column)
    raw: dict

    @property
    def maintainable(self) -> bool:
        return self.overall <= 1


DATA_ENV = "CODEHEALTH_BENCH_DATA"
CSV_RELPATH = Path("ghost-echoes") / "maintainability_data.csv"
SOURCES_RELPATH = Path("sources")
HOW_TO_GET = (
    "See bench/README.md: download maintainability_data.csv from https://zenodo.org/records/12548630 "
    "into $CODEHEALTH_BENCH_DATA/ghost-echoes/ and clone the repositories listed in bench/revisions.json "
    "into $CODEHEALTH_BENCH_DATA/sources/<project>/."
)


class BenchDataError(SystemExit):
    """The benchmark data directory is not configured or incomplete."""


def data_dir() -> Path:
    """``$CODEHEALTH_BENCH_DATA``: holds ``ghost-echoes/maintainability_data.csv`` and ``sources/``."""
    configured = os.environ.get(DATA_ENV, "").strip()
    if not configured:
        raise BenchDataError(f"{DATA_ENV} is not set. {HOW_TO_GET}")
    path = Path(configured).expanduser()
    if not path.is_dir():
        raise BenchDataError(f"{DATA_ENV}={path} is not a directory. {HOW_TO_GET}")
    return path


def default_csv() -> Path:
    path = data_dir() / CSV_RELPATH
    if not path.is_file():
        raise BenchDataError(f"missing {path}. {HOW_TO_GET}")
    return path


def default_sources() -> Path:
    path = data_dir() / SOURCES_RELPATH
    if not path.is_dir():
        raise BenchDataError(f"missing {path}. {HOW_TO_GET}")
    return path


def _num(value: str) -> float | None:
    try:
        return float(value)
    except ValueError:
        return None


def load_rows(csv_path: Path) -> list[Row]:
    with open(csv_path, encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh, delimiter=";")
        return [
            Row(project=r["projectname"], package_and_class=r["packageandclass"], path=r["path"],
                overall=int(r["Overall"]), reference_score=float(r[REFERENCE_COLUMN]), loc=_num(r[LOC_COLUMN]), raw=r)
            for r in reader
        ]


def csv_components(path: str) -> list[str]:
    """Path components of a CSV path below ``<project>/sourcefiles/``."""
    parts = [p for p in re.split(r"[\\/]+", path) if p]
    return parts[2:] if len(parts) > 2 else parts


def package_suffix(package_and_class: str) -> str:
    """``a.b.C`` -> ``a/b/C.java`` (the path suffix every match must end with)."""
    return package_and_class.replace(".", "/") + ".java"


def _common_tail(a: list[str], b: list[str]) -> int:
    n = 0
    while n < min(len(a), len(b)) and a[-1 - n] == b[-1 - n]:
        n += 1
    return n


def match_path(row_path: str, package_and_class: str, repo_files: list[str]) -> str | None:
    """Pick the repo file for a CSV row.

    A candidate must end with the package path suffix. Among candidates, the
    one sharing the longest trailing run of path components with the CSV path
    wins (disambiguates e.g. jsweet ``core-lib/es5`` vs ``core-lib/es6``).
    Ties break on the shorter path.
    """
    suffix = "/" + package_suffix(package_and_class)
    cands = [f for f in repo_files if ("/" + f).endswith(suffix)]
    if not cands:
        return None
    want = csv_components(row_path)
    return max(cands, key=lambda f: (_common_tail(want, f.split("/")), -len(f)))


def code_loc(source: str) -> int:
    """Non-blank lines after removing ``/* */`` and ``//`` comments (approximate)."""
    stripped = re.sub(r"/\*.*?\*/", lambda m: "\n" * m.group(0).count("\n"), source, flags=re.DOTALL)
    stripped = re.sub(r"//[^\n]*", "", stripped)
    return sum(1 for line in stripped.split("\n") if line.strip())


# --- git helpers -----------------------------------------------------------

def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True,
                          text=True, errors="replace").stdout


def list_files(repo: Path, rev: str) -> list[str]:
    return [f for f in git(repo, "ls-tree", "-r", "--name-only", rev).split("\n") if f.endswith(".java")]


def read_blobs(repo: Path, rev: str, paths: list[str]) -> dict[str, str]:
    """Read many files at ``rev`` with one ``git cat-file --batch`` call."""
    if not paths:
        return {}
    req = "".join(f"{rev}:{p}\n" for p in paths).encode()
    out = subprocess.run(["git", "-C", str(repo), "cat-file", "--batch"], input=req, check=True,
                         capture_output=True).stdout
    result: dict[str, str] = {}
    pos = 0
    for p in paths:
        nl = out.index(b"\n", pos)
        header = out[pos:nl].split()
        pos = nl + 1
        if len(header) < 3 or header[1] == b"missing":
            continue
        size = int(header[2])
        result[p] = out[pos:pos + size].decode("utf-8", errors="replace")
        pos += size + 1
    return result


def match_rows(repo: Path, rev: str, rows: list[Row]) -> dict[int, tuple[str, str]]:
    """Index of row -> (repo path, source) for rows found at ``rev``."""
    files = list_files(repo, rev)
    paths = {i: match_path(r.path, r.package_and_class, files) for i, r in enumerate(rows)}
    found = {i: p for i, p in paths.items() if p}
    blobs = read_blobs(repo, rev, sorted(set(found.values())))
    return {i: (p, blobs[p]) for i, p in found.items() if p in blobs}


def loc_agreement(rows: list[Row], matched: dict[int, tuple[str, str]]) -> dict:
    """Match-rate summary: exact LoC match, within 10%, mismatched, missing."""
    exact = within10 = 0
    for i, (_, src) in matched.items():
        want, got = rows[i].loc, code_loc(src)
        if want is None:
            continue
        exact += got == want
        within10 += abs(got - want) <= 0.1 * want
    n = len(rows)
    return {"rows": n, "found": len(matched), "missing": n - len(matched), "loc_exact": exact,
            "loc_within_10pct": within10}
