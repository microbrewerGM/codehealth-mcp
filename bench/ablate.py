"""Ablation: rescore the benchmark with one provider or smell disabled at a time.

Reuses the per-file findings cached by ``bench.run_bench`` (no re-parsing):
a disabled smell's findings are dropped and the file is rescored with
codehealth.score's constants. Dropping is an approximation for composite
rules: e.g. without Brain Method the Complex Method findings it absorbed do
not come back.

Usage: uv run python -m bench.ablate [--no-write]
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import UTC, datetime

from codehealth import score as score_mod
from codehealth import smells as s

from . import metrics as m
from .report import fmt
from .run_bench import RESULTS_MD, THRESHOLD, Scored, load_cache

SIZE_TERM = "file size term"

# Provider groups (DESIGN.md, analyzer table). Single smells are added below.
PROVIDERS: dict[str, frozenset[str]] = {
    "lizard metrics": frozenset({s.COMPLEX_METHOD, s.LARGE_METHOD, s.OVERALL_COMPLEXITY, s.FILE_LOC,
                                 s.FUNCTION_COUNT, SIZE_TERM}),
    "PMD CPD": frozenset({s.DUPLICATION}),
    "PMD GodClass": frozenset({s.BRAIN_CLASS}),
    "tree-sitter (all own smells)": frozenset({s.BUMPY_ROAD, s.COMPLEX_CONDITIONAL, s.LOW_COHESION, s.DEEP_NESTING}),
}


@dataclass(frozen=True)
class Variant:
    name: str
    disabled: frozenset[str]


def variants(smells: set[str]) -> list[Variant]:
    found = [Variant(f"provider: {name}", group) for name, group in PROVIDERS.items()]
    found += [Variant(f"smell: {smell}", frozenset({smell})) for smell in sorted(smells)]
    return found + [Variant(f"term: {SIZE_TERM}", frozenset({SIZE_TERM}))]


def rescore(scored: Scored, disabled: frozenset[str]) -> float:
    kept = [f for f in scored.findings if f["smell"] not in disabled]
    penalties = ((f["key"], score_mod.SMELL_IMPACT.get(f["smell"], 1.0) * f["severity"] * f["weight"]) for f in kept)
    size = 0.0 if SIZE_TERM in disabled else scored.size
    return score_mod.score_from_penalty(score_mod.capped_total(penalties) + score_mod.FILE_SIZE_WEIGHT * size)


def evaluate_variant(files: list[Scored], disabled: frozenset[str]) -> dict:
    return m.evaluate([f.row.maintainable for f in files], [rescore(f, disabled) for f in files], THRESHOLD)


def ablate(files: list[Scored]) -> list[dict]:
    """Baseline row first, then one row per variant with deltas against the baseline."""
    base = evaluate_variant(files, frozenset())
    rows = [{"variant": "none (all enabled)", "f1": base["uc2"]["f1"], "auc": base["auc"], "d_f1": 0.0, "d_auc": 0.0}]
    for v in variants({f["smell"] for x in files for f in x.findings}):
        ev = evaluate_variant(files, v.disabled)
        rows.append({"variant": v.name, "f1": ev["uc2"]["f1"], "auc": ev["auc"],
                     "d_f1": ev["uc2"]["f1"] - base["uc2"]["f1"], "d_auc": ev["auc"] - base["auc"]})
    return rows


def _signed(x: float) -> str:
    return f"{x:+.3f}"


def render(rows: list[dict], n: int) -> str:
    stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    out = [f"## Ablation {stamp}", "",
           (f"n = {n}, cached findings of the last benchmark run, current score.py constants. "
            "Each row disables one provider or smell; negative deltas mean it helps."), "",
           "| disabled | UC2 F1 | delta F1 | AUC | delta AUC |", "|---|---|---|---|---|"]
    out += [f"| {r['variant']} | {fmt(r['f1'])} | {_signed(r['d_f1'])} | {fmt(r['auc'])} | {_signed(r['d_auc'])} |"
            for r in rows]
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--no-write", action="store_true", help="print only; do not append to results.md")
    args = ap.parse_args(argv)
    files = load_cache()
    text = render(ablate(files), len(files))
    print(text)
    if not args.no_write:
        with open(RESULTS_MD, "a") as fh:
            fh.write(text + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
