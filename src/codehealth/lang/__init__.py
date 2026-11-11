"""Language registry.

Every language lizard reads is supported (function metrics). A subset also
has a tree-sitter adapter, which adds the smells only our own code measures.
"""

from __future__ import annotations

from functools import cache
from pathlib import Path

from .. import lizard_metrics
from .base import ClassInfo, Comment, FunctionInfo, LanguageAdapter, ParsedFile
from .go import GoAdapter
from .java import JavaAdapter
from .javascript import JavaScriptAdapter, TsxAdapter, TypeScriptAdapter
from .python import PythonAdapter

_ADAPTER_TYPES: tuple[type[LanguageAdapter], ...] = (
    PythonAdapter,
    JavaScriptAdapter,
    TypeScriptAdapter,
    TsxAdapter,
    JavaAdapter,
    GoAdapter,
)

ADAPTER_EXTENSIONS: dict[str, str] = {ext: a.spec.name for a in _ADAPTER_TYPES for ext in a.spec.extensions}
ADAPTER_LANGUAGES = frozenset(ADAPTER_EXTENSIONS.values())

# Tree-sitter adapters win where both know a suffix (e.g. .jsx is our "javascript").
EXTENSIONS: dict[str, str] = {
    ext: language for ext, (language, _) in lizard_metrics.extension_map().items()
} | ADAPTER_EXTENSIONS


class UnsupportedLanguageError(ValueError):
    pass


def language_for(path: str | Path) -> str | None:
    return EXTENSIONS.get(Path(path).suffix.lower())


def is_supported(path: str | Path) -> bool:
    return language_for(path) is not None


def has_adapter(language: str) -> bool:
    """True when our tree-sitter adapter covers ``language``."""
    return language in ADAPTER_LANGUAGES


@cache
def adapter_for(language: str) -> LanguageAdapter:
    for adapter_type in _ADAPTER_TYPES:
        if adapter_type.spec.name == language:
            return adapter_type()
    raise UnsupportedLanguageError(f"unsupported language: {language}")


def require_language(path: str | Path) -> str:
    language = language_for(path)
    if language is None:
        supported = ", ".join(sorted(EXTENSIONS))
        raise UnsupportedLanguageError(f"unsupported file type: {Path(path).suffix or path} (supported: {supported})")
    return language


def parse_source(source: str, path: str | Path) -> ParsedFile:
    """Parse with the tree-sitter adapter; raises for languages without one."""
    language = require_language(path)
    if not has_adapter(language):
        raise UnsupportedLanguageError(f"no tree-sitter adapter for {language}")
    return adapter_for(language).parse(source)


__all__ = [
    "ClassInfo",
    "Comment",
    "ADAPTER_LANGUAGES",
    "EXTENSIONS",
    "FunctionInfo",
    "LanguageAdapter",
    "ParsedFile",
    "UnsupportedLanguageError",
    "adapter_for",
    "has_adapter",
    "is_supported",
    "language_for",
    "parse_source",
    "require_language",
]
