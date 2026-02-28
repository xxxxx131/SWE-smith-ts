"""
Base class for JavaScript procedural modifications.

Supports both JavaScript and TypeScript files via automatic parser selection.
"""

from abc import ABC
from functools import lru_cache

from swesmith.bug_gen.procedural.base import ProceduralModifier
from swesmith.constants import CodeEntity
from tree_sitter import Language, Parser


@lru_cache(maxsize=4)
def _get_language(ext: str) -> Language:
    """Get tree-sitter Language for the given file extension. Cached for performance."""
    if ext in ("ts",):
        import tree_sitter_typescript as tsts
        return Language(tsts.language_typescript())
    elif ext in ("tsx",):
        import tree_sitter_typescript as tsts
        return Language(tsts.language_tsx())
    else:
        # Default: JavaScript (covers .js, .jsx, and any unknown)
        import tree_sitter_javascript as tsjs
        return Language(tsjs.language())


def get_parser_for_entity(code_entity: CodeEntity) -> Parser:
    """Create a tree-sitter Parser appropriate for the code entity's file type.

    Uses TypeScript parser for .ts/.tsx files, JavaScript parser otherwise.
    This ensures correct AST parsing for TypeScript type annotations, generics, etc.
    """
    lang = _get_language(code_entity.ext)
    return Parser(lang)


class JavaScriptProceduralModifier(ProceduralModifier, ABC):
    """Base class for JavaScript-specific procedural modifications using tree-sitter AST.

    Also handles TypeScript files by selecting the correct parser based on file extension.
    """

    pass
