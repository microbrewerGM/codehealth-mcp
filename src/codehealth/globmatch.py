"""Glob matching for ``matching_content_path`` without regex backtracking.

Patterns come from repository files, which are untrusted. Matching works on
``/``-separated segments with a memoized table, so the cost is bounded by
pattern segments x path segments, and each segment match is a linear-space
wildcard comparison. ``**`` as a whole segment matches zero or more
directories; ``*`` and ``?`` never cross ``/``.
"""

from __future__ import annotations

import re
from functools import lru_cache

MAX_PATTERN_LENGTH = 512
MAX_WILDCARDS = 32
GLOBSTAR = "**"

_STAR_RUN = re.compile(r"\*+")


class GlobError(ValueError):
    pass


def normalize(pattern: str) -> tuple[str, ...]:
    """Split into segments, collapse ``*`` runs and repeated ``**`` segments, enforce limits."""
    if len(pattern) > MAX_PATTERN_LENGTH:
        raise GlobError(f"glob longer than {MAX_PATTERN_LENGTH} characters")
    segments = _collapse(pattern.split("/"))
    if sum(_wildcards(s) for s in segments) > MAX_WILDCARDS:
        raise GlobError(f"glob has more than {MAX_WILDCARDS} wildcards")
    return tuple(segments)


def _collapse(raw_segments: list[str]) -> list[str]:
    segments: list[str] = []
    for raw in raw_segments:
        segment = GLOBSTAR if raw == GLOBSTAR else _STAR_RUN.sub("*", raw)
        if segment != GLOBSTAR or segments[-1:] != [GLOBSTAR]:
            segments.append(segment)
    return segments


def _wildcards(segment: str) -> int:
    return 1 if segment == GLOBSTAR else segment.count("*") + segment.count("?")


def validate(pattern: str) -> str | None:
    """Return an error message for an unusable pattern, else None."""
    try:
        normalize(pattern)
    except GlobError as exc:
        return str(exc)
    return None


def segment_match(pattern: str, text: str) -> bool:
    """Wildcard match of one segment (``*``, ``?``) in O(len(pattern) * len(text)) time."""
    p = t = 0
    star, resume = -1, 0
    while t < len(text):
        token = pattern[p] if p < len(pattern) else ""
        if token == "*":
            star, resume = p, t
            p += 1
        elif token in ("?", text[t]):
            p, t = p + 1, t + 1
        elif star < 0:
            return False
        else:
            p, resume = star + 1, resume + 1
            t = resume
    return set(pattern[p:]) <= {"*"}


def glob_match(pattern: str, relpath: str) -> bool:
    segments = normalize(pattern)
    parts = tuple(relpath.split("/"))

    @lru_cache(maxsize=None)
    def match(i: int, j: int) -> bool:
        if i == len(segments):
            return j == len(parts)
        if segments[i] == GLOBSTAR:
            return match(i + 1, j) or (j < len(parts) and match(i, j + 1))
        return j < len(parts) and segment_match(segments[i], parts[j]) and match(i + 1, j + 1)

    return match(0, 0)
