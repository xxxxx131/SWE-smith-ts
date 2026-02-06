"""
Base classes and utilities for procedural bug generation across different languages.

This module provides the foundational infrastructure for language-specific procedural
modification techniques. Language-specific implementations should be placed in their
respective subdirectories (e.g., python/, javascript/, java/).
"""

# For backward compatibility, expose Python-specific classes
from swesmith.bug_gen.procedural.golang import MODIFIERS_GOLANG
from swesmith.bug_gen.procedural.python import MODIFIERS_PYTHON
from swesmith.bug_gen.procedural.javascript import MODIFIERS_JAVASCRIPT
from swesmith.bug_gen.procedural.rust import MODIFIERS_RUST

# Phase 1: TypeScript reuses JavaScript modifiers (TS is a superset of JS)
# The modifiers operate on runtime logic, not type annotations, so they
# work correctly on TypeScript code (2026-02-03)
MODIFIERS_TYPESCRIPT = MODIFIERS_JAVASCRIPT

MAP_EXT_TO_MODIFIERS = {
    ".go": MODIFIERS_GOLANG,
    ".py": MODIFIERS_PYTHON,
    ".js": MODIFIERS_JAVASCRIPT,
    # Phase 2: Added JSX support for completeness (2026-02-03)
    ".jsx": MODIFIERS_JAVASCRIPT,
    ".rs": MODIFIERS_RUST,
    # Phase 1: Added TypeScript/TSX support (2026-02-03)
    ".ts": MODIFIERS_TYPESCRIPT,
    ".tsx": MODIFIERS_TYPESCRIPT,
}
