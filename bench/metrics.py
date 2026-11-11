"""Classification and rank metrics (pure Python, no numpy)."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence

THRESHOLD = 9.0  # predict "maintainable" at score >= 9 (Borg et al.)


def confusion(actual: Sequence[bool], predicted: Sequence[bool]) -> dict[str, int]:
    pairs = Counter(zip(map(bool, actual), map(bool, predicted)))
    return {"tp": pairs[True, True], "fp": pairs[False, True], "fn": pairs[True, False], "tn": pairs[False, False]}


def f_beta(precision: float, recall: float, beta: float = 1.0) -> float:
    b2 = beta * beta
    denom = b2 * precision + recall
    return (1 + b2) * precision * recall / denom if denom else 0.0


def classification(actual: Sequence[bool], predicted: Sequence[bool]) -> dict[str, float]:
    """Accuracy, precision, recall, F1 and F0.5 for the positive class ``True``."""
    c = confusion(actual, predicted)
    p = c["tp"] / (c["tp"] + c["fp"]) if c["tp"] + c["fp"] else 0.0
    r = c["tp"] / (c["tp"] + c["fn"]) if c["tp"] + c["fn"] else 0.0
    n = len(actual)
    return {
        "n": n,
        **c,
        "accuracy": (c["tp"] + c["tn"]) / n if n else 0.0,
        "precision": p,
        "recall": r,
        "f1": f_beta(p, r, 1.0),
        "f0_5": f_beta(p, r, 0.5),
    }


def auc(scores: Sequence[float], positive: Sequence[bool]) -> float:
    """ROC AUC: probability a positive outscores a negative (ties count 0.5)."""
    ranks = rankdata(scores)
    n_pos = sum(positive)
    n_neg = len(positive) - n_pos
    if not n_pos or not n_neg:
        return float("nan")
    rank_sum = sum(r for r, p in zip(ranks, positive) if p)
    return (rank_sum - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg)


def rankdata(values: Sequence[float]) -> list[float]:
    """Average ranks (1-based), ties share the mean rank."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        mean = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = mean
        i = j + 1
    return ranks


def pearson(x: Sequence[float], y: Sequence[float]) -> float:
    n = len(x)
    if n < 2:
        return float("nan")
    mx, my = sum(x) / n, sum(y) / n
    sxy = sum((a - mx) * (b - my) for a, b in zip(x, y))
    sxx = sum((a - mx) ** 2 for a in x)
    syy = sum((b - my) ** 2 for b in y)
    return sxy / (sxx * syy) ** 0.5 if sxx and syy else float("nan")


def spearman(x: Sequence[float], y: Sequence[float]) -> float:
    return pearson(rankdata(x), rankdata(y))


def evaluate(maintainable: Sequence[bool], score: Sequence[float], threshold: float = 9.0) -> dict:
    """UC1, UC2 and AUC for a higher-is-better score thresholded at ``threshold``."""
    predicted = [s >= threshold for s in score]
    uc1 = classification(maintainable, predicted)
    uc2 = classification([not m for m in maintainable], [not p for p in predicted])
    return {
        "uc1": {k: uc1[k] for k in ("accuracy", "precision", "recall", "f1", "tp", "fp", "fn", "tn")},
        "uc2": {k: uc2[k] for k in ("precision", "recall", "f1", "f0_5")},
        "auc": auc(score, maintainable),
    }
