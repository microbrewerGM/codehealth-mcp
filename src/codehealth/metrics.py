"""Raw metrics for one file. No thresholds live here.

Per-function size and complexity come from lizard (:mod:`codehealth.lizard_metrics`).
Our own tree-sitter code measures only what lizard does not: chunks of nested
logic (Bumpy Road), logical operators per condition (Complex Conditional),
LCOM4 class cohesion, and nesting depth where lizard's ``nd`` value is not
reliable (indentation-delimited languages such as Python).
"""

from __future__ import annotations

import bisect
from collections.abc import Iterator
from dataclasses import dataclass, field

from tree_sitter import Node

from .lang.base import CALL, ClassInfo, FunctionInfo, LanguageSpec, ParsedFile, node_key, text_of
from .lizard_metrics import LizardFile, LizardFunction, nesting_is_reliable

CONSTRUCTOR_NAMES = frozenset({"__init__", "__new__", "__post_init__", "constructor", "initialize", "init"})
SELF_PARAMS = frozenset({"self", "cls"})


@dataclass
class FunctionMetrics:
    """One function: lizard metrics plus tree-sitter-only measures (None = not measured)."""

    name: str  # display name, qualified with enclosing scopes
    identity: str  # stable identity for delta matching (scope + ordinal)
    start_line: int
    end_line: int
    cyclomatic_complexity: int
    lines_of_code: int
    arguments: int
    cognitive_complexity: int
    nesting_depth: int | None
    is_constructor: bool = False
    is_override: bool = False
    syntax: FunctionInfo | None = None  # tree-sitter view, when the language has an adapter
    bumps: list[int] | None = None
    complex_conditionals: list[tuple[int, int]] | None = None


@dataclass
class FileMetrics:
    lines_of_code: int
    function_count: int
    mean_cyclomatic_complexity: float
    functions: list[FunctionMetrics]
    cohesion: dict[str, Cohesion] = field(default_factory=dict)


@dataclass
class Measured:
    """One measured file: its language, tree-sitter view (if any) and metrics."""

    language: str
    parsed: ParsedFile | None
    metrics: FileMetrics


# ----- traversal helpers ---------------------------------------------------
def iter_own(parsed: ParsedFile, root: Node) -> Iterator[Node]:
    """Yield descendants of ``root`` without entering nested functions."""
    stack = list(reversed(root.children))
    while stack:
        node = stack.pop()
        if node_key(node) in parsed.function_keys:
            continue
        yield node
        stack.extend(reversed(node.children))


def _is_else_if(node: Node, spec: LanguageSpec) -> bool:
    parent = node.parent
    if parent is None or node.type not in spec.if_types:
        return False
    if parent.type == "else_clause":
        return True
    return parent.type in spec.if_types and parent.child_by_field_name("alternative") == node


def adds_nesting(node: Node, spec: LanguageSpec) -> bool:
    return node.type in spec.nesting_types and not _is_else_if(node, spec)


def is_logical(node: Node, spec: LanguageSpec) -> bool:
    if node.type not in spec.logical_node_types:
        return False
    return text_of(node.child_by_field_name("operator")) in spec.logical_operators


def nesting_depth(parsed: ParsedFile, root: Node, include_root: bool = False) -> int:
    start = 1 if include_root and adds_nesting(root, parsed.spec) else 0
    deepest = start
    stack = [(child, start) for child in root.children]
    while stack:
        node, depth = stack.pop()
        if node_key(node) in parsed.function_keys:
            continue
        if adds_nesting(node, parsed.spec):
            depth += 1
            deepest = max(deepest, depth)
        stack.extend((child, depth) for child in node.children)
    return deepest


def top_level_statements(parsed: ParsedFile, body: Node | None) -> list[Node]:
    if body is None:
        return []
    statements = [c for c in body.named_children if c.type not in parsed.spec.comment_types]
    if len(statements) == 1 and statements[0].type == "statement_list":
        return top_level_statements(parsed, statements[0])
    return statements


def bumpy_road(parsed: ParsedFile, fn: FunctionInfo, min_depth: int) -> list[int]:
    """Return the max nesting depth of each bump (run of deeply nested statements)."""
    bumps: list[int] = []
    in_bump = False
    for statement in top_level_statements(parsed, fn.body):
        depth = nesting_depth(parsed, statement, include_root=True)
        if depth < min_depth:
            in_bump = False
        elif in_bump:
            bumps[-1] = max(bumps[-1], depth)
        else:
            bumps.append(depth)
            in_bump = True
    return bumps


def _condition_of(node: Node) -> Node | None:
    """The tested expression; Python's ``a if cond else b`` has no ``condition`` field."""
    if node.type == "conditional_expression":
        parts = node.named_children
        return parts[1] if len(parts) > 1 else None
    return node.child_by_field_name("condition")


def logical_operator_count(parsed: ParsedFile, node: Node) -> int:
    own = 1 if is_logical(node, parsed.spec) else 0
    return own + sum(1 for n in iter_own(parsed, node) if is_logical(n, parsed.spec))


def complex_conditionals(parsed: ParsedFile, fn: FunctionInfo, min_operators: float) -> list[tuple[int, int]]:
    """Return (line, operator count) for each condition with many logical operators."""
    found: list[tuple[int, int]] = []
    for node in iter_own(parsed, fn.node):
        if node.type not in parsed.spec.condition_types:
            continue
        condition = _condition_of(node)
        count = logical_operator_count(parsed, condition) if condition is not None else 0
        if count >= min_operators:
            found.append((condition.start_point[0] + 1, count))
    return found


# ----- class cohesion ------------------------------------------------------
@dataclass(frozen=True)
class Cohesion:
    lcom4: int  # connected components that hold instance state
    methods: int  # methods inside those components


def cohesion(cls: ClassInfo) -> Cohesion:
    """LCOM4 over the methods that use instance state (rule in DESIGN.md, "Low Cohesion").

    Nodes are the class's cohesion methods (no constructors, static/class
    methods, dunder/object-protocol methods) and its instance fields; a method
    is linked to each field it reads or writes and to each sibling method it
    calls or references. Accessor-only methods (one-statement getters and
    setters) are not nodes: a call to one counts as a use of its field.
    Components without any instance field (stateless helpers, overrides that
    ignore ``self``) are dropped. A class without instance fields has no
    LCOM4 (0). Linear in the number of member references.
    """
    if not cls.fields:
        return Cohesion(0, 0)
    methods = set(cls.member_refs) - cls.accessors
    forest = _cohesion_graph(cls, methods)
    stateful = {forest.find(("f", f)) for f in cls.fields}
    kept = [root for root in (forest.find(("m", m)) for m in methods) if root in stateful]
    return Cohesion(len(set(kept)), len(kept))


def _cohesion_graph(cls: ClassInfo, methods: set[str]) -> _UnionFind:
    accessor_field = {a: f for a in cls.accessors for f in cls.member_refs[a] & cls.fields}
    forest = _UnionFind([("m", m) for m in methods] + [("f", f) for f in cls.fields])
    for method in methods:
        for target in _cohesion_links(cls.member_refs[method], methods, accessor_field, cls.fields):
            forest.union(("m", method), target)
    return forest


def _cohesion_links(refs: set[str], methods: set[str], accessor_field: dict[str, str], fields: set[str]) -> Iterator[tuple]:
    for ref in refs:
        name = ref.removesuffix(CALL)
        if name in methods:
            yield ("m", name)
        elif name in accessor_field:
            yield ("f", accessor_field[name])
        elif ref in fields:
            yield ("f", ref)


def lcom4(cls: ClassInfo) -> int:
    return cohesion(cls).lcom4


class _UnionFind:
    def __init__(self, items: list):
        self.parent = {item: item for item in items}

    def find(self, item):
        while self.parent[item] != item:
            self.parent[item] = self.parent[self.parent[item]]
            item = self.parent[item]
        return item

    def union(self, a, b) -> None:
        self.parent[self.find(a)] = self.find(b)


# ----- function inventory: lizard functions mapped onto tree-sitter identities ---------
class _SyntaxIndex:
    """Tree-sitter functions grouped by short name and sorted by start line."""

    ANONYMOUS = "(anonymous)"

    def __init__(self, parsed: ParsedFile):
        self.groups: dict[str, list[FunctionInfo]] = {}
        for fn in parsed.functions:  # sorted by start line
            key = self.ANONYMOUS if fn.name.startswith("<anonymous@") else fn.name.rsplit(".", 1)[-1]
            self.groups.setdefault(key, []).append(fn)
        self.starts = {key: [f.start_line for f in fns] for key, fns in self.groups.items()}
        self.used: set[int] = set()

    def match(self, lz: LizardFunction) -> FunctionInfo | None:
        """The innermost unused function with lizard's name that holds lizard's start line."""
        key = self.ANONYMOUS if lz.name == self.ANONYMOUS else lz.unqualified_name
        group = self.groups.get(key, [])
        index = bisect.bisect_right(self.starts.get(key, []), lz.start_line)
        for position in range(index - 1, -1, -1):
            fn = group[position]
            if id(fn) not in self.used and fn.end_line >= lz.start_line:
                self.used.add(id(fn))
                return fn
        return None


def _is_syntax_constructor(parsed: ParsedFile, fn: FunctionInfo) -> bool:
    if fn.node.type in ("constructor_declaration", "compact_constructor_declaration"):
        return True
    return fn.class_name is not None and fn.name in parsed.spec.constructor_names


def _is_lizard_constructor(lz: LizardFunction) -> bool:
    parts = lz.qualified_name.split(".")
    return lz.unqualified_name in CONSTRUCTOR_NAMES or (len(parts) > 1 and parts[-1] == parts[-2])


def _argument_count(lz: LizardFunction, language: str) -> int:
    """lizard's count, without a leading Python ``self``/``cls`` (fallback when there is no syntax match)."""
    has_self = language == "python" and bool(set(lz.parameters[:1]) & SELF_PARAMS)
    return max(lz.parameter_count - has_self, 0)


def _nesting(lz: LizardFunction, language: str, parsed: ParsedFile | None, syntax: FunctionInfo | None) -> int | None:
    """Tree-sitter depth of control structures when we have the syntax; lizard ``nd`` otherwise.

    lizard's ``nd`` also counts ``&&``/``||`` (see DESIGN.md), so it is only a
    fallback for brace languages without an adapter.
    """
    if parsed is not None:
        # lizard's nd pass is skipped when we have a parse (see analysis.measure_source).
        return nesting_depth(parsed, syntax.node) if syntax is not None else None
    if nesting_is_reliable(language):
        return lz.max_nesting_depth
    return None


class _Identities:
    """Identity for lizard-only functions: lizard scope plus an ordinal, never a line number."""

    def __init__(self, taken: set[str]):
        self.taken = set(taken)
        self.ordinals: dict[str, int] = {}

    def make(self, lz: LizardFunction) -> str:
        label = "<anonymous>" if lz.name == "(anonymous)" else lz.qualified_name
        while True:
            ordinal = self.ordinals.get(label, 0)
            self.ordinals[label] = ordinal + 1
            identity = label if ordinal == 0 else f"{label}#{ordinal}"
            if identity not in self.taken:
                self.taken.add(identity)
                return identity


def function_inventory(lz_file: LizardFile, parsed: ParsedFile | None, thresholds: dict[str, float]) -> list[FunctionMetrics]:
    index = _SyntaxIndex(parsed) if parsed is not None else None
    ordered = sorted(lz_file.functions, key=lambda f: (f.start_line, -f.end_line))
    matches = [(lz, index.match(lz) if index is not None else None) for lz in ordered]
    builder = _Builder(lz_file.language if parsed is None else parsed.language, parsed, thresholds)
    builder.identities = _Identities({syntax.identity for _, syntax in matches if syntax is not None})
    return [builder.build(lz, syntax) for lz, syntax in matches]


class _Builder:
    def __init__(self, language: str, parsed: ParsedFile | None, thresholds: dict[str, float]):
        self.language, self.parsed, self.t = language, parsed, thresholds
        self.identities = _Identities(set())

    def build(self, lz: LizardFunction, syntax: FunctionInfo | None) -> FunctionMetrics:
        fm = FunctionMetrics(
            name=lz.qualified_name,
            identity="",
            start_line=lz.start_line,
            end_line=lz.end_line,
            cyclomatic_complexity=lz.cyclomatic_complexity,
            lines_of_code=lz.nloc,
            arguments=_argument_count(lz, self.language),
            cognitive_complexity=lz.cognitive_complexity,
            nesting_depth=_nesting(lz, self.language, self.parsed, syntax),
        )
        if syntax is None or self.parsed is None:
            fm.identity, fm.is_constructor = self.identities.make(lz), _is_lizard_constructor(lz)
            return fm
        self._add_syntax(fm, syntax, self.parsed)
        return fm

    def _add_syntax(self, fm: FunctionMetrics, syntax: FunctionInfo, parsed: ParsedFile) -> None:
        fm.name, fm.identity, fm.syntax = syntax.qualified_name, syntax.identity, syntax
        fm.start_line, fm.end_line = syntax.start_line, syntax.end_line
        fm.is_constructor = _is_syntax_constructor(parsed, syntax)
        fm.arguments, fm.is_override = len(syntax.params), syntax.is_override
        fm.bumps = bumpy_road(parsed, syntax, int(self.t["function_bumpy_road_nesting_level_depth"]))
        fm.complex_conditionals = complex_conditionals(parsed, syntax, self.t["function_complex_conditional_branches_warning"])


# ----- file metrics --------------------------------------------------------------
def file_metrics(lz_file: LizardFile, parsed: ParsedFile | None, thresholds: dict[str, float]) -> FileMetrics:
    functions = function_inventory(lz_file, parsed, thresholds)
    total_cc = sum(m.cyclomatic_complexity for m in functions)
    classes = parsed.classes if parsed is not None else []
    return FileMetrics(
        lines_of_code=lz_file.nloc,
        function_count=len(functions),
        mean_cyclomatic_complexity=round(total_cc / len(functions), 2) if functions else 0.0,
        functions=functions,
        cohesion={cls.identity: cohesion(cls) for cls in classes if cls.member_refs},
    )
