"""Go adapter. Methods are grouped into pseudo-classes by receiver type."""

from __future__ import annotations

from tree_sitter import Node

from .base import CALL, ClassInfo, FunctionInfo, LanguageAdapter, LanguageSpec, is_call_target, text_of

_PARAM_TYPES = frozenset({"parameter_declaration", "variadic_parameter_declaration"})


class GoAdapter(LanguageAdapter):
    spec = LanguageSpec(
        name="go",
        grammar="go",
        extensions=(".go",),
        function_types=frozenset({"function_declaration", "method_declaration"}),
        class_types=frozenset(),
        comment_types=frozenset({"comment"}),
        nesting_types=frozenset(
            {"if_statement", "for_statement", "expression_switch_statement", "type_switch_statement", "select_statement"}
        ),
        if_types=frozenset({"if_statement"}),
        condition_types=frozenset({"if_statement", "for_statement"}),
        logical_node_types=frozenset({"binary_expression"}),
        logical_operators=frozenset({"&&", "||"}),
    )

    def function_name(self, node: Node) -> str | None:
        """``Type.Method`` for methods, the plain name for functions."""
        name = text_of(node.child_by_field_name("name"))
        return ".".join(filter(None, (_receiver_type(node), name))) if name else None

    def params(self, node: Node, is_method: bool) -> list[str]:
        """One entry per declared name (``a, b int`` is two); unnamed parameters count as ``_``."""
        decls = [d for d in self.parameter_nodes(node) if d.type in _PARAM_TYPES]
        return [name for decl in decls for name in _declared_names(decl)]

    def finish_classes(self, functions: list[FunctionInfo], classes: list[ClassInfo]) -> list[ClassInfo]:
        by_type: dict[str, ClassInfo] = {}
        for fn in functions:
            receiver = _receiver_type(fn.node)
            if not receiver:
                continue
            cls = by_type.setdefault(receiver, ClassInfo(receiver, receiver, fn.start_line, fn.end_line))
            cls.start_line = min(cls.start_line, fn.start_line)
            cls.end_line = max(cls.end_line, fn.end_line)
            cls.methods.append(fn)
            fn.class_name = receiver
        return classes + list(by_type.values())

    def member_refs(self, method: FunctionInfo, cls: ClassInfo) -> set[str]:
        receiver = _receiver_name(method.node)
        if method.body is None or not receiver:
            return set()
        refs = {_receiver_ref(node, receiver) for node in self.iter_own(method.body, set())} - {""}
        return {f"{cls.name}.{ref}" for ref in refs}


def _receiver_ref(node: Node, receiver: str) -> str:
    """``f`` for ``r.f``, ``f()`` for ``r.f(...)`` where ``r`` is the receiver, otherwise ``""``."""
    if node.type != "selector_expression" or text_of(node.child_by_field_name("operand")) != receiver:
        return ""
    name = text_of(node.child_by_field_name("field"))
    return name + CALL if is_call_target(node) else name


def _declared_names(decl: Node) -> list[str]:
    return [text_of(n) for n in decl.children_by_field_name("name")] or ["_"]


def _receiver_decl(node: Node) -> Node | None:
    receiver = node.child_by_field_name("receiver")
    children = receiver.named_children if receiver is not None else []
    return next((c for c in children if c.type == "parameter_declaration"), None)


def _receiver_type(node: Node) -> str | None:
    decl = _receiver_decl(node)
    type_node = decl.child_by_field_name("type") if decl is not None else None
    while type_node is not None and type_node.type in ("pointer_type", "generic_type"):
        type_node = _inner_type(type_node)
    return text_of(type_node) or None


def _inner_type(node: Node) -> Node | None:
    """``T`` inside ``*T`` or ``T[K]``."""
    return next((c for c in node.named_children if c.type in ("type_identifier", "generic_type")), None)


def _receiver_name(node: Node) -> str | None:
    decl = _receiver_decl(node)
    if decl is None:
        return None
    return text_of(decl.child_by_field_name("name")) or None
