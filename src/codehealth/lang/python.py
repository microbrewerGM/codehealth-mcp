"""Python adapter."""

from __future__ import annotations

from tree_sitter import Node

from .base import CALL, ClassInfo, FunctionInfo, LanguageAdapter, LanguageSpec, first_identifier, is_call_target, text_of

_SKIP_PARAMS = frozenset({"keyword_separator", "positional_separator", "comment"})
_STATIC_DECORATORS = frozenset({"staticmethod", "classmethod"})


class PythonAdapter(LanguageAdapter):
    spec = LanguageSpec(
        name="python",
        grammar="python",
        extensions=(".py", ".pyi"),
        function_types=frozenset({"function_definition"}),
        class_types=frozenset({"class_definition"}),
        comment_types=frozenset({"comment"}),
        nesting_types=frozenset(
            {"if_statement", "for_statement", "while_statement", "try_statement", "match_statement", "with_statement"}
        ),
        if_types=frozenset({"if_statement"}),
        condition_types=frozenset({"if_statement", "elif_clause", "while_statement", "conditional_expression"}),
        logical_node_types=frozenset({"boolean_operator"}),
        logical_operators=frozenset({"and", "or"}),
        constructor_names=frozenset({"__init__", "__new__", "__post_init__"}),
        self_names=frozenset({"self", "cls"}),
    )

    def parameter_nodes(self, node: Node) -> list[Node]:
        return [p for p in super().parameter_nodes(node) if p.type not in _SKIP_PARAMS]

    def params(self, node: Node, is_method: bool) -> list[str]:
        return self.without_self([first_identifier(p) for p in self.parameter_nodes(node)], is_method)

    def member_refs(self, method: FunctionInfo, cls: ClassInfo) -> set[str]:
        if method.body is None:
            return set()
        return {_self_ref(node, self.spec.self_names) for node in self.iter_own(method.body, set())} - {""}

    def is_static(self, method: FunctionInfo) -> bool:
        return bool(_decorators(method) & _STATIC_DECORATORS)

    def is_override(self, node: Node) -> bool:
        return any(d.rsplit(".", 1)[-1] == "override" for d in _decorator_names(node))

    def is_property(self, method: FunctionInfo) -> bool:
        return any(d == "property" or d.endswith((".setter", ".getter")) for d in _decorators(method))

    def declared_fields(self, cls: ClassInfo) -> set[str]:
        """Annotated class-body names (``x: int`` / ``x: int = 0``), e.g. dataclass fields."""
        return {name for name, annotated in _class_assignments(cls) if annotated}

    def class_constants(self, cls: ClassInfo) -> set[str]:
        return {name for name, annotated in _class_assignments(cls) if not annotated}


def _self_ref(node: Node, self_names: frozenset[str]) -> str:
    """``x`` for ``self.x``, ``x()`` for ``self.x(...)``, otherwise ``""``."""
    if node.type != "attribute":
        return ""
    if text_of(node.child_by_field_name("object")) not in self_names:
        return ""
    name = text_of(node.child_by_field_name("attribute"))
    return name + CALL if is_call_target(node) else name


def _decorators(method: FunctionInfo) -> set[str]:
    return _decorator_names(method.node)


def _decorator_names(node: Node) -> set[str]:
    parent = node.parent
    if parent is None or parent.type != "decorated_definition":
        return set()
    return {text_of(d).lstrip("@").split("(")[0].strip() for d in parent.named_children if d.type == "decorator"}


def _class_assignments(cls: ClassInfo) -> list[tuple[str, bool]]:
    """(name, annotated) for each simple assignment directly in the class body."""
    body = cls.node.child_by_field_name("body") if cls.node is not None else None
    found = (_simple_assignment(stmt) for stmt in (body.named_children if body is not None else []))
    return [item for item in found if item is not None]


def _simple_assignment(stmt: Node) -> tuple[str, bool] | None:
    """(name, annotated) for ``name = ...`` / ``name: T = ...``; None for anything else."""
    node = stmt.named_children[0] if stmt.type == "expression_statement" and stmt.named_children else stmt
    if node.type != "assignment":
        return None
    left = node.child_by_field_name("left")
    if left is None or left.type != "identifier":
        return None
    return text_of(left), node.child_by_field_name("type") is not None
