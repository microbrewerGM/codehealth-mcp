"""Static documentation for explain_code_health (our own wording)."""

from __future__ import annotations

from . import score
from .smells import HINTS

OVERVIEW = (
    "Code Health is a 1-10 maintainability score per file. lizard measures every function "
    "(cyclomatic complexity, lines of code, argument count, nesting depth, cognitive complexity) "
    "in about 30 languages. Our tree-sitter code adds chunks of nested logic, logical operators "
    "per condition and class cohesion (LCOM4) for Python, JavaScript, TypeScript/TSX, Java and Go. "
    "PMD, when installed, adds copy-paste detection (CPD) and, for Java, God Class detection. "
    "Each metric over its threshold becomes a finding; the analyzers field of a review says which "
    "smells could not be measured. Thresholds come from public per-language defaults where "
    "available and can be overridden in .codehealth/rules.json."
)


SCORE = (
    f"Each finding has a severity in (0, 1] that grows with the log of how far the value exceeds "
    f"its threshold. Penalty = smell impact x severity x rule weight; per-function penalties are "
    f"capped at {score.FUNCTION_PENALTY_CAP} per function. File size adds {score.FILE_SIZE_WEIGHT} per "
    f"file-LoC-warning lines (e.g. 1000 for Java) of code beyond one acceptable function "
    f"(file_size_penalty; delta verdicts ignore it). Score = 1 + 9 * exp(-{score.K} * total penalty), "
    f"rounded to 2 decimals. Bands: 10.0 optimal, >= {score.HEALTHY_MIN} Healthy, "
    f">= {score.WARNING_MIN} Warning, below that Alert."
)

DIRECTIVES = (
    "Put a comment with @codehealth(disable:\"Complex Method\") or @codehealth(disable-all) "
    "right before a function to skip function-level smells "
    "for that function only. File-level smells cannot be disabled this way; set the rule "
    "weight to 0 in the rules file instead."
)


TOPICS = {
    "": OVERVIEW, "overview": OVERVIEW, "model": OVERVIEW,
    "score": SCORE, "scoring": SCORE, "bands": SCORE,
    "directives": DIRECTIVES, "disable": DIRECTIVES, "config": DIRECTIVES,
}


def explain(topic: str) -> dict:
    key = topic.strip().lower()
    text = TOPICS[key] if key in TOPICS else _smell_text(key)
    return {"topic": topic or "overview", "text": text}


def _smell_text(key: str) -> str:
    for smell, hint in HINTS.items():
        if smell.lower() == key:
            return f"{smell}: {hint}"
    options = ", ".join(sorted(HINTS))
    return f"Unknown topic. Try 'overview', 'score', 'directives' or a smell name: {options}."
