"""JavaScript, TypeScript and TSX adapters (shared ECMAScript tables)."""

from __future__ import annotations

from tree_sitter import Node

from .base import (
    CALL,
    ClassInfo,
    FunctionInfo,
    LanguageAdapter,
    LanguageSpec,
    first_identifier,
    has_modifier,
    is_call_target,
    text_of,
)

_FUNCTIONS = frozenset({"function_declaration", "generator_function_declaration", "method_definition"})
_NAMED_ONLY = frozenset({"arrow_function", "function_expression", "function", "generator_function"})
_CLASSES = frozenset({"class_declaration", "class", "abstract_class_declaration"})
_NESTING = frozenset(
    {"if_statement", "for_statement", "for_in_statement", "while_statement", "do_statement", "switch_statement", "try_statement"}
)
_CONDITIONS = frozenset({"if_statement", "while_statement", "do_statement", "ternary_expression"})
_NAME_HOLDERS = {
    "variable_declarator": "name",
    "pair": "key",
    "assignment_expression": "left",
    "public_field_definition": "name",
    "field_definition": "property",
}


def _ecma_spec(name: str, extensions: tuple[str, ...]) -> LanguageSpec:
    return LanguageSpec(
        name=name,
        grammar=name,
        extensions=extensions,
        function_types=_FUNCTIONS,
        named_only_function_types=_NAMED_ONLY,
        class_types=_CLASSES,
        comment_types=frozenset({"comment"}),
        nesting_types=_NESTING,
        if_types=frozenset({"if_statement"}),
        condition_types=_CONDITIONS,
        logical_node_types=frozenset({"binary_expression"}),
        logical_operators=frozenset({"&&", "||", "??"}),
        constructor_names=frozenset({"constructor"}),
        self_names=frozenset({"this"}),
        owner_reset_types=frozenset({"object"}),
        protocol_methods=frozenset({"toString", "valueOf", "toJSON"}),
    )


class JavaScriptAdapter(LanguageAdapter):
    spec = _ecma_spec("javascript", (".js", ".jsx", ".mjs", ".cjs"))

    def function_name(self, node: Node) -> str | None:
        if node.type in _FUNCTIONS:
            return text_of(node.child_by_field_name("name")) or None
        return self._assigned_name(node)

    def _assigned_name(self, node: Node) -> str | None:
        parent = node.parent
        if parent is None or parent.type not in _NAME_HOLDERS:
            return None
        holder = parent.child_by_field_name(_NAME_HOLDERS[parent.type])
        if holder is None or holder == node:
            return None
        return text_of(holder).split(".")[-1] or None

    def parameter_nodes(self, node: Node) -> list[Node]:
        single = node.child_by_field_name("parameter")
        if single is not None:
            return [single]
        return super().parameter_nodes(node)

    def params(self, node: Node, is_method: bool) -> list[str]:
        return [first_identifier(p) for p in self.parameter_nodes(node)]

    def member_refs(self, method: FunctionInfo, cls: ClassInfo) -> set[str]:
        if method.body is None:
            return set()
        return {_this_ref(node) for node in self.iter_own(method.body, set())} - {""}

    def is_override(self, node: Node) -> bool:
        return any(c.type == "override_modifier" for c in node.children)

    def is_static(self, method: FunctionInfo) -> bool:
        holder = method.node if method.node.type == "method_definition" else method.node.parent
        return holder is not None and has_modifier(holder, "static")

    def declared_fields(self, cls: ClassInfo) -> set[str]:
        return {name for name, static in _field_definitions(cls) if not static}

    def class_constants(self, cls: ClassInfo) -> set[str]:
        return {name for name, static in _field_definitions(cls) if static}


def _this_ref(node: Node) -> str:
    """``x`` for ``this.x``, ``x()`` for ``this.x(...)``, otherwise ``""``."""
    if node.type != "member_expression":
        return ""
    obj = node.child_by_field_name("object")
    if obj is None or obj.type != "this":
        return ""
    name = text_of(node.child_by_field_name("property"))
    return name + CALL if is_call_target(node) else name


def _field_definitions(cls: ClassInfo) -> list[tuple[str, bool]]:
    """(name, is_static) for each field defined in the class body."""
    body = cls.node.child_by_field_name("body") if cls.node is not None else None
    found = []
    for member in body.named_children if body is not None else []:
        if member.type in ("field_definition", "public_field_definition"):
            name = member.child_by_field_name("property") or member.child_by_field_name("name")
            found.append((text_of(name), has_modifier(member, "static")))
    return found


class TypeScriptAdapter(JavaScriptAdapter):
    spec = _ecma_spec("typescript", (".ts", ".mts", ".cts"))


class TsxAdapter(JavaScriptAdapter):
    spec = _ecma_spec("tsx", (".tsx",))
