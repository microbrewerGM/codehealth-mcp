"""Markdown rendering of a benchmark run (see bench.run_bench)."""

from __future__ import annotations

import math
from dataclasses import dataclass

from .metrics import THRESHOLD

APPROACHES = (("codehealth (ours) >= 9", "ours"), ("published reference score (Ghost Echoes, Borg et al. 2024) >= 9", "baseline_reference_ge_9"),
              ("LoC (nos) <= 275", "baseline_loc_le_275"))


def fmt(x: float | None) -> str:
    return "n/a" if x is None or math.isnan(x) else f"{x:.3f}"


def _sources(summary: dict) -> list[str]:
    out = ["### Sources and match rate", "",
           "| project | revision | commit | date | found | missing | LoC exact | LoC within 10% |",
           "|---|---|---|---|---|---|---|---|"]
    for p, s in summary["projects"].items():
        out.append(f"| {p} | {s['label']} | `{s['commit'][:10]}` | {s['date']} | {s['found']}/{s['rows']} | "
                   f"{s['missing']} | {s['loc_exact']} | {s['loc_within_10pct']} |")
    for p, s in summary["excluded"].items():
        out.append(f"| {p} | excluded: {s['reason']} | | | 0/{s['rows']} | {s['rows']} | | |")
    out += ["", ("LoC agreement compares comment-stripped non-blank lines with the CSV `nos` column "
                 "(the CSV `line` column is not a line count; `nos` reproduces the paper's LoC baseline)."), ""]
    if summary["errors"]:
        out += [f"Errors: {len(summary['errors'])} files failed to score.", ""]
    return out


def headline_row(name: str, r: dict) -> str:
    uc1, uc2 = r["uc1"], r["uc2"]
    cells = [uc1["accuracy"], uc1["precision"], uc1["recall"], uc1["f1"],
             uc2["precision"], uc2["recall"], uc2["f1"], uc2["f0_5"], r["auc"]]
    return f"| {name} | " + " | ".join(fmt(c) for c in cells) + " |"


def _headline(ev: dict, summary: dict) -> list[str]:
    out = ["### Headline", "",
           "| approach | UC1 acc | UC1 P | UC1 R | UC1 F1 | UC2 P | UC2 R | UC2 F1 | UC2 F0.5 | AUC |",
           "|---|---|---|---|---|---|---|---|---|---|"]
    out += [headline_row(name, ev[key]) for name, key in APPROACHES]
    human = ", ".join(f"{d} {fmt(v)}" for d, v in ev["spearman_vs_human"].items())
    out += ["", ("Spearman rho, ours vs published reference score (Ghost Echoes, Borg et al. 2024): "
             f"{fmt(ev['spearman_vs_reference'])}."),
            (f"Spearman rho, ours vs human dimensions (0 = best, so negative is good): {human}. "
             f"Reference score vs Overall: {fmt(ev['spearman_reference_vs_human_overall'])}.")]
    if "runtime_seconds" in summary:
        out.append(f"Runtime (match + review, one PMD batch): {summary['runtime_seconds']:.0f} s.")
    return out + [""]


REFERENCE_NOTE = ("reference = published reference score (Ghost Echoes, Borg et al. 2024), "
                  "shipped in the replication package (Zenodo 12548630); comparison only.")


def _per_project(ev: dict) -> list[str]:
    out = ["### Per project (UC2 F1 / AUC)", "",
           "| project | n | ours UC2 F1 | ours AUC | reference UC2 F1 | reference AUC |", "|---|---|---|---|---|---|"]
    for p, r in ev["per_project"].items():
        out.append(f"| {p} | {r['n']} | {fmt(r['ours']['uc2']['f1'])} | {fmt(r['ours']['auc'])} | "
                   f"{fmt(r['reference']['uc2']['f1'])} | {fmt(r['reference']['auc'])} |")
    return out + ["", REFERENCE_NOTE, ""]


def _smells(smells: list[dict]) -> list[str]:
    out = ["### Per smell (share of files where the smell fires)", "",
           "| smell | maintainable | non-maintainable | lift | total penalty |", "|---|---|---|---|---|"]
    for r in smells:
        out.append(f"| {r['smell']} | {r['maintainable_files']} ({fmt(r['maintainable_rate'])}) | "
                   f"{r['non_maintainable_files']} ({fmt(r['non_maintainable_rate'])}) | {fmt(r['lift'])} | "
                   f"{r['total_penalty']:.1f} |")
    return out + [""]


def _errors(scored: list) -> list[str]:
    missed = sum(1 for s in scored if not s.row.maintainable and s.score >= THRESHOLD)
    flagged = sum(1 for s in scored if s.row.maintainable and s.score < THRESHOLD)
    return [(f"Missed non-maintainable files (score >= {THRESHOLD}): {missed}; "
             f"maintainable files flagged (score < {THRESHOLD}): {flagged}."), ""]


@dataclass(frozen=True)
class BenchRun:
    """Everything one benchmark section reports."""

    stamp: str
    summary: dict
    ev: dict
    smells: list[dict]
    scored: list


def render_markdown(run: BenchRun) -> str:
    ev = run.ev
    intro = (f"Scored {ev['n']} files ({ev['maintainable']} maintainable). Threshold {THRESHOLD}. "
             "Ground truth: human Overall <= 1.")
    out = [f"## Run {run.stamp}", "", intro, ""]
    out += _sources(run.summary) + _headline(ev, run.summary) + _per_project(ev) + _smells(run.smells)
    return "\n".join(out + _errors(run.scored)) + "\n"
