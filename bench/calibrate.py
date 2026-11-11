"""Calibrate OUR scoring constants against the HUMAN labels with 5-fold CV.

Tunes ``K``, ``FUNCTION_PENALTY_CAP``, ``FILE_SIZE_WEIGHT`` and
``SMELL_IMPACT`` (codehealth.score) by coordinate descent on a grid.
Objective on the training folds: UC2 F1 (threshold 9.0) + AUC. Metrics are
reported on pooled held-out folds (stratified 5-fold) and
leave-one-project-out, never in-sample. The dataset's
published reference score (Ghost Echoes, Borg et al. 2024) is not used here
at all.

This script only reports recommended constants; it does not edit score.py.

Usage: uv run python -m bench.calibrate [--folds 5] [--seed 0] [--cached] [--no-write]
(``--cached`` reuses bench/.cache/findings.json from the last bench.run_bench.)
"""

from __future__ import annotations

import argparse
import json
import math
import random
from dataclasses import dataclass, replace
from datetime import UTC, datetime

from codehealth import score as score_mod

from . import metrics as m
from .report import fmt
from .run_bench import HERE, RESULTS_MD, THRESHOLD, Scored, collect, load_cache

K_GRID = (0.03, 0.05, 0.075, 0.1, 0.125, 0.15, 0.2, 0.25, 0.3, 0.4, 0.5)
CAP_GRID = (1.0, 2.0, 3.0, 4.0, 6.0, 8.0, 12.0, 1e9)
SIZE_GRID = (0.0, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0)
IMPACT_GRID = (0.0, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 4.0, 6.0)
MAX_PASSES = 4
CALIBRATION_JSON = HERE / "calibration.json"


@dataclass(frozen=True)
class Params:
    k: float
    cap: float
    size: float
    impact: tuple[tuple[str, float], ...]

    @classmethod
    def defaults(cls) -> Params:
        return cls(score_mod.K, score_mod.FUNCTION_PENALTY_CAP, score_mod.FILE_SIZE_WEIGHT,
                   tuple(sorted(score_mod.SMELL_IMPACT.items())))

    def moved(self, name: str, value: float) -> Params:
        """A copy with one constant changed: ``k``, ``cap``, ``size`` or a smell name."""
        if name in ("k", "cap", "size"):
            return replace(self, **{name: value})
        impact = dict(self.impact) | {name: value}
        return replace(self, impact=tuple(sorted(impact.items())))

    def to_dict(self) -> dict:
        return {"K": self.k, "FUNCTION_PENALTY_CAP": self.cap if self.cap < 1e8 else None,
                "FILE_SIZE_WEIGHT": self.size, "SMELL_IMPACT": dict(self.impact)}


def file_score(s: Scored, p: Params) -> float:
    """Mirror of codehealth.score.code_health with substitutable constants."""
    impact = dict(p.impact)
    penalties = ((f["key"], impact.get(f["smell"], 1.0) * f["severity"] * f["weight"]) for f in s.findings)
    penalty = score_mod.capped_total(penalties, p.cap) + p.size * s.size
    return round(score_mod.MIN_SCORE + (score_mod.MAX_SCORE - score_mod.MIN_SCORE) * math.exp(-p.k * penalty), 2)


def evaluate(files: list[Scored], p: Params) -> dict:
    return m.evaluate([s.row.maintainable for s in files], [file_score(s, p) for s in files], THRESHOLD)


def objective(files: list[Scored], p: Params) -> float:
    ev = evaluate(files, p)
    return ev["uc2"]["f1"] + ev["auc"]


def moves(smells: list[str]) -> list[tuple[str, float]]:
    grids = [("k", K_GRID), ("cap", CAP_GRID), ("size", SIZE_GRID)] + [(s, IMPACT_GRID) for s in smells]
    return [(name, value) for name, grid in grids for value in grid]


def fit(files: list[Scored], start: Params, smells: list[str]) -> Params:
    """Coordinate descent: accept any single-constant move that improves the objective."""
    best, best_obj = start, objective(files, start)
    for _ in range(MAX_PASSES):
        before = best_obj
        for name, value in moves(smells):
            cand = best.moved(name, value)
            obj = objective(files, cand)
            if obj > best_obj + 1e-9:
                best, best_obj = cand, obj
        if best_obj <= before + 1e-9:
            break
    return best


def stratified_folds(files: list[Scored], k: int, seed: int) -> list[list[int]]:
    rng = random.Random(seed)
    folds: list[list[int]] = [[] for _ in range(k)]
    for label in (True, False):
        idx = [i for i, s in enumerate(files) if s.row.maintainable is label]
        rng.shuffle(idx)
        for j, i in enumerate(idx):
            folds[j % k].append(i)
    return folds


def project_groups(files: list[Scored]) -> list[list[int]]:
    projects = sorted({s.row.project for s in files})
    return [[i for i, s in enumerate(files) if s.row.project == p] for p in projects]


def _held_out(files: list[Scored], group: list[int], smells: list[str]) -> tuple[Params, dict[int, float]]:
    held = set(group)
    p = fit([s for i, s in enumerate(files) if i not in held], Params.defaults(), smells)
    return p, {i: file_score(files[i], p) for i in group}


def _summary(per_fold: list[dict]) -> dict:
    f1s = [f["uc2"]["f1"] for f in per_fold]
    aucs = [f["auc"] for f in per_fold if not math.isnan(f["auc"])]
    return {"per_fold_uc2_f1": f1s, "per_fold_auc": aucs, "mean_uc2_f1": sum(f1s) / len(f1s),
            "mean_auc": sum(aucs) / len(aucs) if aucs else float("nan")}


def cross_validate(files: list[Scored], groups: list[list[int]], smells: list[str]) -> dict:
    """Fit on all-but-one group, predict the held-out group; pool predictions."""
    pred: dict[int, float] = {}
    fitted, per_fold = [], []
    for group in groups:
        p, scores = _held_out(files, group, smells)
        pred |= scores
        fitted.append(p.to_dict())
        per_fold.append(m.evaluate([files[i].row.maintainable for i in group], [scores[i] for i in group], THRESHOLD))
    pooled = m.evaluate([s.row.maintainable for s in files], [pred[i] for i in range(len(files))], THRESHOLD)
    return {"pooled": pooled, **_summary(per_fold), "fold_params": fitted}


def _check_mirror(files: list[Scored]) -> None:
    defaults = Params.defaults()
    mismatch = [s.row.package_and_class for s in files if file_score(s, defaults) != s.score]
    if mismatch:
        raise SystemExit(f"file_score does not mirror codehealth.score for {len(mismatch)} files: {mismatch[:3]}")


def _row(name: str, ev: dict) -> str:
    cells = [ev["uc1"]["accuracy"], ev["uc1"]["f1"], ev["uc2"]["precision"], ev["uc2"]["recall"],
             ev["uc2"]["f1"], ev["uc2"]["f0_5"], ev["auc"]]
    return f"| {name} | " + " | ".join(fmt(c) for c in cells) + " |"


def render(report: dict, folds: int, seed: int) -> str:
    cv, lopo = report["cv"], report["leave_one_project_out"]
    md = [f"## Calibration {report['timestamp']}", "",
          (f"Human labels only (Overall <= 1). n = {report['n']}. Objective on training folds: UC2 F1 + AUC. "
           f"Stratified {folds}-fold CV (seed {seed}) and leave-one-project-out; metrics are pooled "
           "held-out predictions. score.py defaults are unchanged."), "",
          "| setting | UC1 acc | UC1 F1 | UC2 P | UC2 R | UC2 F1 | UC2 F0.5 | AUC |", "|---|---|---|---|---|---|---|---|",
          _row("current defaults (no fitting)", report["defaults"]["metrics"]),
          _row(f"{folds}-fold CV (held-out)", cv["pooled"]),
          _row("leave-one-project-out (held-out)", lopo["pooled"]),
          _row("recommended, in-sample (optimistic)", report["recommended"]["in_sample_metrics"]), "",
          (f"Per-fold UC2 F1: {', '.join(fmt(x) for x in cv['per_fold_uc2_f1'])}; "
           f"per-fold AUC: {', '.join(fmt(x) for x in cv['per_fold_auc'])}."), "",
          "Recommended constants (fit on all files):", "", "```json",
          json.dumps(report["recommended"]["params"], indent=2), "```", ""]
    return "\n".join(md) + "\n"


def calibrate(files: list[Scored], folds: int, seed: int) -> dict:
    _check_mirror(files)
    smells = sorted({f["smell"] for s in files for f in s.findings})
    defaults = Params.defaults()
    recommended = fit(files, defaults, smells)
    return {"timestamp": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), "n": len(files), "folds": folds,
            "seed": seed, "objective": "UC2 F1 + AUC at threshold 9.0 on training folds",
            "defaults": {"params": defaults.to_dict(), "metrics": evaluate(files, defaults)},
            "cv": cross_validate(files, stratified_folds(files, folds, seed), smells),
            "leave_one_project_out": {"projects": sorted({s.row.project for s in files}),
                                      **cross_validate(files, project_groups(files), smells)},
            "recommended": {"params": recommended.to_dict(), "in_sample_metrics": evaluate(files, recommended)}}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--folds", type=int, default=5)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--cached", action="store_true", help="reuse findings cached by the last bench.run_bench")
    ap.add_argument("--no-write", action="store_true")
    args = ap.parse_args(argv)
    files = load_cache() if args.cached else collect()[0]
    report = calibrate(files, args.folds, args.seed)
    text = render(report, args.folds, args.seed)
    print(text)
    if not args.no_write:
        CALIBRATION_JSON.write_text(json.dumps(report, indent=2) + "\n")
        with open(RESULTS_MD, "a") as fh:
            fh.write(text + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
