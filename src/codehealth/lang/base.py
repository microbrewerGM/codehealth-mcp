"""Language-neutral adapter over tree-sitter syntax trees.

Each language supplies a :class:`LanguageSpec` (node type tables) and may
override a few hooks for names, parameters and member references. The walker
here turns a syntax tree into functions, classes and comments.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass, field

from tree_sitter import Node, Tree
from tree_sitter_language_pack import get_parser

NodeKey = tuple[int, int, str]

# A member reference ending in CALL is a call (``self.f()``); others are reads/writes.
CALL = "()"
_ACCESSOR_NAME = re.compile(r"^(get|set|is|has)([A-Z_]|$)")


def node_key(node: Node) -> NodeKey:
    return (node.start_byte, node.end_byte, node.type)


def text_of(node: Node | None) -> str:
    if node is None or node.text is None:
        return ""
    return node.text.decode("utf-8", errors="replace")


@dataclass(frozen=True)
class LanguageSpec:
    name: str
    grammar: str
    extensions: tuple[str, ...]
    function_types: frozenset[str]
    class_types: frozenset[str]
    comment_types: frozenset[str]
    nesting_types: frozenset[str]
    if_types: frozenset[str]
    condition_types: frozenset[str]
    logical_node_types: frozenset[str]
    logical_operators: frozenset[str]
    named_only_function_types: frozenset[str] = frozenset()
    constructor_names: frozenset[str] = frozenset()
    self_names: frozenset[str] = frozenset()
    # Nodes whose bodies are anonymous types/objects: their methods do not
    # belong to the enclosing class (e.g. Java anonymous classes, JS object literals).
    owner_reset_types: frozenset[str] = frozenset()
    # Object-protocol methods (``__eq__``, ``toString``...) say nothing about cohesion.
    protocol_methods: frozenset[str] = frozenset()


@dataclass
class FunctionInfo:
    name: str
    qualified_name: str
    start_line: int
    end_line: int
    params: list[str]
    node: Node
    body: Node | None
    class_name: str | None = None
    # Overrides a supertype method (``@Override``, ``@override``, TS ``override``):
    # its signature is dictated by the supertype.
    is_override: bool = False
    # Stable identity for matching across versions: enclosing scopes plus an
    # ordinal among same-named (or anonymous) siblings; never a line number.
    identity: str = ""


@dataclass
class ClassInfo:
    name: str
    qualified_name: str
    start_line: int
    end_line: int
    methods: list[FunctionInfo] = field(default_factory=list)
    # Cohesion inputs (see metrics.cohesion): member references of each method
    # that takes part in LCOM4, the instance fields, and accessor-only methods.
    member_refs: dict[str, set[str]] = field(default_factory=dict)
    identity: str = ""
    fields: set[str] = field(default_factory=set)
    accessors: set[str] = field(default_factory=set)
    node: Node | None = None


@dataclass(frozen=True)
class Comment:
    start_line: int
    end_line: int
    text: str


@dataclass
class ParsedFile:
    language: str
    spec: LanguageSpec
    tree: Tree
    functions: list[FunctionInfo]
    classes: list[ClassInfo]
    comments: list[Comment]
    function_keys: set[NodeKey]


@dataclass
class _Frame:
    node: Node
    scope: tuple[str, ...]
    owner: ClassInfo | None
    id_scope: tuple[str, ...] = ()


@dataclass
class _WalkState:
    functions: list[FunctionInfo] = field(default_factory=list)
    classes: list[ClassInfo] = field(default_factory=list)
    ordinals: dict[tuple[tuple[str, ...], str], int] = field(default_factory=dict)

    def identity_segment(self, id_scope: tuple[str, ...], label: str) -> str:
        key = (id_scope, label)
        ordinal = self.ordinals.get(key, 0)
        self.ordinals[key] = ordinal + 1
        return label if ordinal == 0 else f"{label}#{ordinal}"


class LanguageAdapter:
    """Generic walker; subclasses tune it through ``spec`` and hooks."""

    spec: LanguageSpec

    def __init__(self) -> None:
        self._parser = get_parser(self.spec.grammar)  # type: ignore[arg-type]

    # ----- public API -------------------------------------------------
    def parse(self, source: str) -> ParsedFile:
        tree = self._parser.parse(source.encode("utf-8"))
        functions, classes = self._collect(tree.root_node)
        classes = self.finish_classes(functions, classes)
        for cls in classes:
            self._cohesion_inputs(cls)
        return ParsedFile(
            language=self.spec.name,
            spec=self.spec,
            tree=tree,
            functions=functions,
            classes=classes,
            comments=self._comments(tree.root_node),
            function_keys={node_key(f.node) for f in functions},
        )

    def iter_own(self, root: Node, function_keys: set[NodeKey]) -> Iterator[Node]:
        """Yield ``root``'s descendants, skipping nested function definitions."""
        stack = list(reversed(root.children))
        while stack:
            node = stack.pop()
            if node_key(node) in function_keys:
                continue
            yield node
            stack.extend(reversed(node.children))

    # ----- hooks -------------------------------------------------------
    def function_name(self, node: Node) -> str | None:
        return text_of(node.child_by_field_name("name")) or None

    def class_name(self, node: Node) -> str:
        return text_of(node.child_by_field_name("name")) or "<anonymous>"

    def function_body(self, node: Node) -> Node | None:
        return node.child_by_field_name("body")

    def parameter_nodes(self, node: Node) -> list[Node]:
        params = node.child_by_field_name("parameters")
        if params is None:
            return []
        return [c for c in params.named_children if c.type not in self.spec.comment_types]

    def params(self, node: Node, is_method: bool) -> list[str]:
        return self.without_self([text_of(p) for p in self.parameter_nodes(node)], is_method)

    def without_self(self, names: list[str], is_method: bool) -> list[str]:
        """Drop a method's leading ``self``/``cls``/``this`` parameter."""
        if is_method and set(names[:1]) & self.spec.self_names:
            return names[1:]
        return names

    def member_refs(self, method: FunctionInfo, cls: ClassInfo) -> set[str]:
        """Instance members ``method`` uses; calls end in ``CALL``."""
        return set()

    def is_constructor(self, method: FunctionInfo) -> bool:
        return method.name in self.spec.constructor_names

    def is_static(self, method: FunctionInfo) -> bool:
        """Static/class methods cannot touch instance state."""
        return False

    def is_property(self, method: FunctionInfo) -> bool:
        return False

    def is_override(self, node: Node) -> bool:
        """True when the function is marked as overriding a supertype method."""
        return False

    def declared_fields(self, cls: ClassInfo) -> set[str]:
        """Instance fields declared in the class body."""
        return set()

    def class_constants(self, cls: ClassInfo) -> set[str]:
        """Class-level (static) attributes, which are not instance state."""
        return set()

    def cohesion_methods(self, cls: ClassInfo) -> list[FunctionInfo]:
        return [m for m in cls.methods if self._takes_part(m)]

    def _takes_part(self, method: FunctionInfo) -> bool:
        short = method.name.rsplit(".", 1)[-1]
        dunder = short.startswith("__") and short.endswith("__")
        return not (self.is_constructor(method) or self.is_static(method) or dunder or short in self.spec.protocol_methods)

    def _cohesion_inputs(self, cls: ClassInfo) -> None:
        refs = {id(m): self.member_refs(m, cls) for m in cls.methods if not self.is_static(m)}
        method_names = {m.name for m in cls.methods}
        cls.fields = self._instance_fields(cls, list(refs.values()), method_names)
        participants = self.cohesion_methods(cls)
        for m in participants:
            cls.member_refs.setdefault(m.name, set()).update(refs[id(m)])
        # An overloaded name is an accessor only when every overload is one.
        others = {m.name for m in participants if not self._is_accessor(m, refs[id(m)], cls.fields, method_names)}
        cls.accessors = set(cls.member_refs) - others

    def _instance_fields(self, cls: ClassInfo, ref_sets: list[set[str]], method_names: set[str]) -> set[str]:
        used = {r for found in ref_sets for r in found if not r.endswith(CALL)}
        return (used | self.declared_fields(cls)) - self.class_constants(cls) - method_names

    def _is_accessor(self, method: FunctionInfo, refs: set[str], fields: set[str], methods: set[str]) -> bool:
        """A getter/setter: accessor name or property, one statement, one field, no sibling calls."""
        short = method.name.rsplit(".", 1)[-1]
        if not (_ACCESSOR_NAME.match(short) or self.is_property(method)):
            return False
        touched = refs & fields
        calls = {r.removesuffix(CALL) for r in refs} & methods
        return len(touched) == 1 and not calls and len(self.body_statements(method)) <= 1

    def body_statements(self, method: FunctionInfo) -> list[Node]:
        body = method.body
        if body is None:
            return []
        statements = [c for c in body.named_children if c.type not in self.spec.comment_types]
        if len(statements) == 1 and statements[0].type == "statement_list":
            return [c for c in statements[0].named_children if c.type not in self.spec.comment_types]
        return statements

    def finish_classes(self, functions: list[FunctionInfo], classes: list[ClassInfo]) -> list[ClassInfo]:
        return classes

    def is_function(self, node: Node) -> bool:
        if node.type in self.spec.function_types:
            return True
        return node.type in self.spec.named_only_function_types and self.function_name(node) is not None

    # ----- walking -----------------------------------------------------
    def _collect(self, root: Node) -> tuple[list[FunctionInfo], list[ClassInfo]]:
        state = _WalkState()
        stack: list[tuple[Node, _Frame]] = [(c, _Frame(root, (), None)) for c in reversed(root.children)]
        while stack:  # true pre-order in source order, so ordinals follow the file
            node, parent = stack.pop()
            frame = self._visit(node, parent, state)
            stack.extend((child, frame) for child in reversed(node.children))
        state.functions.sort(key=lambda f: (f.start_line, f.end_line))
        state.classes.sort(key=lambda c: c.start_line)
        return state.functions, state.classes

    def _visit(self, node: Node, frame: _Frame, state: _WalkState) -> _Frame:
        if not node.is_named:
            return frame_for(node, frame)
        if node.type in self.spec.class_types:
            return self._visit_class(node, frame, state)
        if self.is_function(node):
            return self._visit_function(node, frame, state)
        if node.type in self.spec.owner_reset_types:
            return _Frame(node, frame.scope, None, frame.id_scope)
        return frame_for(node, frame)

    def _visit_class(self, node: Node, frame: _Frame, state: _WalkState) -> _Frame:
        cls = self._make_class(node, frame.scope)
        segment = state.identity_segment(frame.id_scope, cls.name)
        cls.identity = ".".join(frame.id_scope + (segment,))
        state.classes.append(cls)
        return _Frame(node, frame.scope + (cls.name,), cls, frame.id_scope + (segment,))

    def _visit_function(self, node: Node, frame: _Frame, state: _WalkState) -> _Frame:
        info = self._make_function(node, frame)
        label = info.name if not info.name.startswith("<anonymous@") else "<anonymous>"
        segment = state.identity_segment(frame.id_scope, label)
        info.identity = ".".join(frame.id_scope + (segment,))
        state.functions.append(info)
        if frame.owner is not None:
            frame.owner.methods.append(info)
        return _Frame(node, frame.scope + (info.name,), None, frame.id_scope + (segment,))

    def _make_class(self, node: Node, scope: tuple[str, ...]) -> ClassInfo:
        name = self.class_name(node)
        return ClassInfo(
            name=name,
            qualified_name=".".join(scope + (name,)),
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
            node=node,
        )

    def _make_function(self, node: Node, frame: _Frame) -> FunctionInfo:
        name = self.function_name(node) or f"<anonymous@{node.start_point[0] + 1}>"
        return FunctionInfo(
            name=name,
            qualified_name=".".join(frame.scope + (name,)),
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
            params=self.params(node, frame.owner is not None),
            node=node,
            body=self.function_body(node),
            class_name=frame.owner.name if frame.owner else None,
            is_override=self.is_override(node),
        )

    def _comments(self, root: Node) -> list[Comment]:
        found = [
            Comment(n.start_point[0] + 1, n.end_point[0] + 1, text_of(n))
            for n in _walk(root)
            if n.type in self.spec.comment_types
        ]
        return sorted(found, key=lambda c: c.start_line)


def frame_for(node: Node, parent: _Frame) -> _Frame:
    return _Frame(node, parent.scope, parent.owner, parent.id_scope)


def _walk(root: Node) -> Iterator[Node]:
    stack = [root]
    while stack:
        node = stack.pop()
        yield node
        stack.extend(reversed(node.children))  # pre-order, source order


def is_call_target(node: Node) -> bool:
    """True when ``node`` is the callee of a call expression (``obj.f`` in ``obj.f()``)."""
    parent = node.parent
    if parent is None or parent.type not in ("call", "call_expression"):
        return False
    callee = parent.child_by_field_name("function")
    return callee is not None and node_key(callee) == node_key(node)


def has_modifier(node: Node, word: str) -> bool:
    """True when ``node`` has a ``word`` keyword child or a modifiers child containing it."""
    return any(word in _modifier_words(child) for child in node.children)


def _modifier_words(child: Node) -> set[str]:
    if child.type == "modifiers":
        return set(text_of(child).split())
    return {child.type}


def first_identifier(node: Node) -> str:
    """Return the first identifier-like leaf text under ``node``."""
    for n in _walk(node):
        if n.child_count == 0 and "identifier" in n.type:
            return text_of(n)
    return text_of(node)
