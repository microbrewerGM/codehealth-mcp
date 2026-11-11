"""Java adapter."""

from __future__ import annotations

from tree_sitter import Node

from .base import CALL, ClassInfo, FunctionInfo, LanguageAdapter, LanguageSpec, first_identifier, has_modifier, text_of

_PARAM_TYPES = frozenset({"formal_parameter", "spread_parameter"})


class JavaAdapter(LanguageAdapter):
    spec = LanguageSpec(
        name="java",
        grammar="java",
        extensions=(".java",),
        function_types=frozenset({"method_declaration", "constructor_declaration", "compact_constructor_declaration"}),
        class_types=frozenset(
            {"class_declaration", "interface_declaration", "enum_declaration", "record_declaration"}
        ),
        comment_types=frozenset({"line_comment", "block_comment"}),
        nesting_types=frozenset(
            {
                "if_statement",
                "for_statement",
                "enhanced_for_statement",
                "while_statement",
                "do_statement",
                "switch_expression",
                "switch_statement",
                "try_statement",
                "try_with_resources_statement",
            }
        ),
        if_types=frozenset({"if_statement"}),
        condition_types=frozenset({"if_statement", "while_statement", "do_statement", "ternary_expression"}),
        logical_node_types=frozenset({"binary_expression"}),
        logical_operators=frozenset({"&&", "||"}),
        self_names=frozenset({"this"}),
        owner_reset_types=frozenset({"object_creation_expression", "enum_constant"}),
        protocol_methods=frozenset({"equals", "hashCode", "toString", "compareTo", "clone", "finalize"}),
    )

    def parameter_nodes(self, node: Node) -> list[Node]:
        return [p for p in super().parameter_nodes(node) if p.type in _PARAM_TYPES]

    def params(self, node: Node, is_method: bool) -> list[str]:
        return [_param_name(p) for p in self.parameter_nodes(node)]

    def is_constructor(self, method: FunctionInfo) -> bool:
        return method.node.type != "method_declaration"

    def is_override(self, node: Node) -> bool:
        modifiers = next((c for c in node.children if c.type == "modifiers"), None)
        if modifiers is None:
            return False
        return any(a.type.endswith("annotation") and _annotation_name(a) == "Override" for a in modifiers.named_children)

    def is_static(self, method: FunctionInfo) -> bool:
        return has_modifier(method.node, "static")

    def declared_fields(self, cls: ClassInfo) -> set[str]:
        return {name for name, static in _field_declarations(_class_body(cls)) if not static}

    def class_constants(self, cls: ClassInfo) -> set[str]:
        return {name for name, static in _field_declarations(_class_body(cls)) if static}

    def member_refs(self, method: FunctionInfo, cls: ClassInfo) -> set[str]:
        fields = {name for name, _ in _field_declarations(method.node.parent)}
        refs: set[str] = set()
        if method.body is None:
            return refs
        for node in self.iter_own(method.body, set()):
            refs.update(_member_ref(node, fields))
        return refs


def _param_name(node: Node) -> str:
    name = node.child_by_field_name("name")
    return text_of(name) if name is not None else first_identifier(node)


def _annotation_name(node: Node) -> str:
    return text_of(node.child_by_field_name("name")).rsplit(".", 1)[-1]


def _class_body(cls: ClassInfo) -> Node | None:
    return cls.node.child_by_field_name("body") if cls.node is not None else None


def _field_declarations(class_body: Node | None) -> list[tuple[str, bool]]:
    """(name, is_static) for each field declared directly in ``class_body``."""
    if class_body is None:
        return []
    found = []
    for decl in class_body.named_children:
        if decl.type == "field_declaration":
            static = has_modifier(decl, "static")
            found += [(text_of(var.child_by_field_name("name")), static) for var in decl.children_by_field_name("declarator")]
    return found


def _member_ref(node: Node, fields: set[str]) -> set[str]:
    handler = _MEMBER_REFS.get(node.type)
    return handler(node, fields) if handler else set()


def _this_field(node: Node, fields: set[str]) -> set[str]:
    if text_of(node.child_by_field_name("object")) != "this":
        return set()
    return {text_of(node.child_by_field_name("field"))}


def _own_call(node: Node, fields: set[str]) -> set[str]:
    if text_of(node.child_by_field_name("object")) not in ("", "this"):  # unqualified or this.f()
        return set()
    return {text_of(node.child_by_field_name("name")) + CALL}


def _field_name(node: Node, fields: set[str]) -> set[str]:
    name = text_of(node)
    return {name} if name in fields else set()


_MEMBER_REFS = {"field_access": _this_field, "method_invocation": _own_call, "identifier": _field_name}
