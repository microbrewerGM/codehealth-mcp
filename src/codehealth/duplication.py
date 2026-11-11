"""Map PMD CPD duplications onto functions ("Code Duplication").

CPD reports duplicated token runs as line ranges. A pair of functions is a
duplicate when one CPD block covers at least ``min_similarity`` of each
function's line span; that share is the finding's value. Code outside
functions is not reported (see DESIGN.md, gaps).

Where CPD cannot normalise identifiers and literals (``TOKEN_LANGUAGES``),
renamed copies are found from tree-sitter tokens instead: identifiers become
``ID``, literals ``LIT``, comments are dropped. Candidate pairs share a
winnowed k-gram fingerprint; their similarity is the share of each
function's tokens inside common runs (the smaller share). CPD stays primary:
a function pair it reports is not reported again.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from difflib import SequenceMatcher
from itertools import combinations

from tree_sitter import Node

from .lang.base import ParsedFile, node_key
from .metrics import FunctionMetrics
from .pmd import Duplication, Occurrence
from .smells import DuplicatePair


@dataclass(frozen=True)
class LocatedPair:
    first_path: str
    second_path: str
    pair: DuplicatePair


def _span(fm: FunctionMetrics) -> int:
    return fm.end_line - fm.start_line + 1


def _overlap(a_start: int, a_end: int, b_start: int, b_end: int) -> int:
    return max(0, min(a_end, b_end) - max(a_start, b_start) + 1)


def _within(functions: list[FunctionMetrics], occ: Occurrence) -> list[FunctionMetrics]:
    return [f for f in functions if _overlap(f.start_line, f.end_line, occ.start_line, occ.end_line)]


def _counterpart(fm: FunctionMetrics, src: Occurrence, dst: Occurrence, candidates: list[FunctionMetrics]) -> FunctionMetrics | None:
    """The function in ``dst`` that sits where ``fm`` sits in ``src``."""
    shift = dst.start_line - src.start_line
    best, best_overlap = None, 0
    for g in candidates:
        overlap = _overlap(g.start_line, g.end_line, fm.start_line + shift, fm.end_line + shift)
        if overlap > best_overlap:
            best, best_overlap = g, overlap
    return best


def _coverage(fm: FunctionMetrics, occ: Occurrence) -> float:
    return _overlap(fm.start_line, fm.end_line, occ.start_line, occ.end_line) / _span(fm)


@dataclass(frozen=True)
class Limits:
    min_loc: float
    min_similarity: float  # 0..1

    def accepts(self, smaller_loc: float, similarity: float) -> bool:
        return smaller_loc >= self.min_loc and similarity >= self.min_similarity


def _is_self_match(fm: FunctionMetrics, other: FunctionMetrics, ends: tuple[Occurrence, Occurrence]) -> bool:
    """A block overlapping itself inside one function is not a duplicate pair."""
    return other is fm and ends[0].path == ends[1].path


def map_duplications(
    duplications: list[Duplication],
    functions_by_path: dict[str, list[FunctionMetrics]],
    min_loc: float,
    min_similarity: float,
) -> list[LocatedPair]:
    """Function pairs covered by CPD blocks, deduplicated, in a stable order."""
    limits = Limits(min_loc, min_similarity)
    best: dict[tuple, LocatedPair] = {}
    for dup, src, dst in _occurrence_pairs(duplications, functions_by_path):
        for located in _pairs_for(dup, (src, dst), functions_by_path, limits):
            key = (located.first_path, located.pair.first.identity, located.second_path, located.pair.second.identity)
            if key not in best or located.pair.similarity > best[key].pair.similarity:
                best[key] = located
    return sorted(best.values(), key=lambda p: (p.first_path, p.pair.first.start_line, p.second_path, p.pair.second.start_line))


def _occurrence_pairs(duplications: list[Duplication], functions_by_path: dict) -> list[tuple]:
    pairs = []
    for dup in duplications:
        occurrences = [o for o in dup.occurrences if o.path in functions_by_path]
        pairs += [(dup, src, dst) for i, src in enumerate(occurrences) for dst in occurrences[i + 1 :]]
    return pairs


def _pairs_for(dup: Duplication, ends: tuple[Occurrence, Occurrence], functions_by_path: dict, limits: Limits) -> list[LocatedPair]:
    src, dst = ends
    targets = _within(functions_by_path[dst.path], dst)
    found = []
    for fm in _within(functions_by_path[src.path], src):
        other = _counterpart(fm, src, dst, targets)
        if other is None or _is_self_match(fm, other, ends):
            continue
        similarity = round(min(_coverage(fm, src), _coverage(other, dst)), 3)
        if not limits.accepts(min(fm.lines_of_code, other.lines_of_code), similarity):
            continue
        first, second = sorted([(src.path, fm), (dst.path, other)], key=lambda side: (side[0], side[1].start_line))
        found.append(LocatedPair(first[0], second[0], DuplicatePair(first[1], second[1], similarity, dup.lines, dup.tokens)))
    return found


# ----- renamed clones from normalized tree-sitter tokens ---------------------------------------
# CPD's Python, ECMAScript, TypeScript and Go lexers ignore --ignore-identifiers
# and --ignore-literals (verified with PMD 7.29.0; the Java lexer honours them),
# so renamed copies in these languages come from our own token comparison.
TOKEN_LANGUAGES = frozenset({"python", "javascript", "typescript", "tsx", "go"})
TOKEN_PROVIDER = "tree-sitter:tokens"
KGRAM = 5
WINNOW_WINDOW = 4
# Fingerprints shared by more functions than this are boilerplate; skipping
# them keeps candidate generation near-linear on very large files.
MAX_FINGERPRINT_FANOUT = 50
_LITERAL_TYPES = frozenset({"integer", "float", "number", "true", "false"})


@dataclass(frozen=True)
class Candidate:
    """A function big enough to check, with its normalized tokens and winnowed fingerprints."""

    path: str
    function: FunctionMetrics
    tokens: tuple[str, ...]
    prints: frozenset[int]


def normalized_tokens(parsed: ParsedFile, root: Node) -> list[str]:
    """Leaf tokens of ``root``: identifiers -> ID, literals -> LIT, comments and nested functions dropped."""
    tokens: list[str] = []
    stack = list(reversed(root.children))
    while stack:
        node = stack.pop()
        if node.type in parsed.spec.comment_types or node_key(node) in parsed.function_keys:
            continue
        token = _token_class(node)
        if token is None:
            stack.extend(reversed(node.children))
        else:
            tokens.append(token)
    return tokens


def _is_literal(kind: str) -> bool:
    return "string" in kind or kind.endswith("literal") or kind in _LITERAL_TYPES


def _token_class(node: Node) -> str | None:
    """Named nodes only: anonymous keyword tokens such as TypeScript's ``string`` type stay as they are."""
    if node.is_named and _is_literal(node.type):
        return "LIT"  # whole literal, including string interpolation
    if node.child_count:
        return None
    return "ID" if node.is_named and "identifier" in node.type else node.type


def fingerprints(tokens: list[str]) -> frozenset[int]:
    """Winnowed hashes of token k-grams (Schleimer et al., 2003)."""
    grams = [_digest(" ".join(tokens[i : i + KGRAM])) for i in range(len(tokens) - KGRAM + 1)]
    if len(grams) <= WINNOW_WINDOW:
        return frozenset(grams)
    return frozenset(min(grams[i : i + WINNOW_WINDOW]) for i in range(len(grams) - WINNOW_WINDOW + 1))


def _digest(text: str) -> int:
    return int.from_bytes(hashlib.blake2b(text.encode(), digest_size=8).digest(), "big")


def candidates(path: str, parsed: ParsedFile | None, functions: list[FunctionMetrics], min_loc: float) -> list[Candidate]:
    if parsed is None or parsed.language not in TOKEN_LANGUAGES:
        return []
    found = []
    for fm in functions:
        if fm.syntax is not None and fm.lines_of_code >= min_loc:
            tokens = normalized_tokens(parsed, fm.syntax.node)
            found.append(Candidate(path, fm, tuple(tokens), fingerprints(tokens)))
    return found


def token_similarity(a: tuple[str, ...], b: tuple[str, ...]) -> tuple[float, int]:
    """Share of each side's tokens inside common runs of at least KGRAM tokens (the smaller share), and that run length."""
    blocks = SequenceMatcher(None, a, b, autojunk=False).get_matching_blocks()
    matched = sum(block.size for block in blocks if block.size >= KGRAM)
    return (min(matched / len(a), matched / len(b)) if a and b else 0.0), matched


def token_pairs(found: list[Candidate], limits: Limits, min_tokens: float) -> list[LocatedPair]:
    """Function pairs whose normalized token streams are alike (``limits``) over at least ``min_tokens`` tokens.

    ``min_tokens`` is CPD's minimum block size: it keeps out functions whose
    lines are mostly one literal (e.g. tests built around a source string).
    """
    pairs = []
    for i, j in sorted(_sharing_pairs([c.prints for c in found])):
        a, b = found[i], found[j]
        similarity, matched = token_similarity(a.tokens, b.tokens)
        similarity = round(similarity, 3)
        if matched >= min_tokens and limits.accepts(min(a.function.lines_of_code, b.function.lines_of_code), similarity):
            first, second = sorted([a, b], key=lambda c: (c.path, c.function.start_line))
            lines = min(_span(a.function), _span(b.function))
            pair = DuplicatePair(first.function, second.function, similarity, lines, matched, TOKEN_PROVIDER)
            pairs.append(LocatedPair(first.path, second.path, pair))
    return pairs


def _sharing_pairs(prints: list[frozenset[int]]) -> set[tuple[int, int]]:
    """Index pairs that share a fingerprint (inverted index), skipping boilerplate fingerprints."""
    pairs: set[tuple[int, int]] = set()
    for owners in _postings(prints).values():
        if 1 < len(owners) <= MAX_FINGERPRINT_FANOUT:
            pairs.update(combinations(owners, 2))
    return pairs


def _postings(prints: list[frozenset[int]]) -> dict[int, list[int]]:
    postings: dict[int, list[int]] = {}
    for index, fingerprint_set in enumerate(prints):
        for fingerprint in fingerprint_set:
            postings.setdefault(fingerprint, []).append(index)
    return postings


def pair_key(located: LocatedPair) -> tuple:
    return (located.first_path, located.pair.first.identity, located.second_path, located.pair.second.identity)


def merge_pairs(primary: list[LocatedPair], extra: list[LocatedPair]) -> list[LocatedPair]:
    """``primary`` (CPD) plus the ``extra`` pairs it does not already report: one finding per function pair."""
    seen = {pair_key(p) for p in primary}
    merged = primary + [p for p in extra if pair_key(p) not in seen]
    return sorted(merged, key=lambda p: (p.first_path, p.pair.first.start_line, p.second_path, p.pair.second.start_line))
