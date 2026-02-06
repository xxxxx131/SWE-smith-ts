"""
TypeScript Code Entity Adapter for SWE-smith.

This module provides TypeScriptEntity class for parsing and analyzing TypeScript
source code using tree-sitter-typescript. It inherits from JavaScriptEntity to
reuse the property analysis logic, as TypeScript is a superset of JavaScript.

Created: 2026-02-03
Phase: Phase 1 - TypeScript Environment Construction

Key Features:
- Uses tree-sitter-typescript for AST parsing
- Inherits all JavaScript property analysis
- Strictly aligned with Python's python.py entity extraction:
  Only collects executable code entities (functions, methods, classes)
  that can have logical bugs introduced
  
Note: Pure type definitions (interface_declaration, type_alias_declaration)
are NOT collected for bug generation as they have no executable code body
that can be modified to introduce logical bugs. This aligns with how Python's
adapter only collects ClassDef and FunctionDef.
"""

import warnings

import tree_sitter_typescript as tsts

from swesmith.constants import CodeEntity, CodeProperty
from swesmith.bug_gen.adapters.javascript import JavaScriptEntity
from swesmith.bug_gen.adapters.utils import build_entity
from tree_sitter import Language, Parser


# Initialize TypeScript language parser
# tree-sitter-typescript provides both TypeScript and TSX languages
TS_LANGUAGE = Language(tsts.language_typescript())
TSX_LANGUAGE = Language(tsts.language_tsx())


class TypeScriptEntity(JavaScriptEntity):
    """
    Code entity for TypeScript source code.
    
    Inherits from JavaScriptEntity since TypeScript is a superset of JavaScript.
    All JavaScript property analysis logic is reused. Additional handling is
    provided for TypeScript-specific constructs.
    """

    def _analyze_properties(self):
        """
        Analyze TypeScript code properties.
        
        Calls parent JavaScript analysis first, then adds TypeScript-specific
        property detection.
        """
        # First, run JavaScript property analysis (handles most cases)
        super()._analyze_properties()
        
        # Add TypeScript-specific entity type detection
        node = self.node
        
        # TypeScript-specific declarations
        if node.type == "interface_declaration":
            self._tags.add(CodeProperty.IS_CLASS)  # Treat interfaces like classes
        elif node.type == "type_alias_declaration":
            pass  # Type aliases are metadata, not executable code
        elif node.type == "enum_declaration":
            self._tags.add(CodeProperty.IS_CLASS)  # Treat enums like classes

    @property
    def name(self) -> str:
        """
        Extract name from TypeScript node.
        
        Extends JavaScript name extraction with TypeScript-specific node types.
        In TypeScript, class names use `type_identifier` instead of `identifier`.
        """
        # Handle TypeScript-specific declarations
        if self.node.type == "interface_declaration":
            return self._find_child_text("type_identifier")
        if self.node.type == "type_alias_declaration":
            return self._find_child_text("type_identifier")
        if self.node.type == "enum_declaration":
            return self._find_child_text("identifier")
        # TypeScript class declarations use type_identifier for class names
        if self.node.type == "class_declaration":
            return self._find_child_text("type_identifier")
        
        # Fall back to JavaScript name extraction
        return super().name

    @property
    def signature(self) -> str:
        """
        Extract signature from TypeScript node.
        
        Handles TypeScript-specific declarations that have different body types.
        """
        # For TypeScript-specific declarations, find the body and return everything before
        if self.node.type in ["interface_declaration", "enum_declaration"]:
            for child in self.node.children:
                if child.type in ["interface_body", "enum_body", "object_type"]:
                    body_start_byte = child.start_byte - self.node.start_byte
                    signature = self.src_code[:body_start_byte].strip()
                    if signature.endswith(" {"):
                        signature = signature[:-2].strip()
                    return signature
        
        # For type aliases, return the full declaration without the type definition
        if self.node.type == "type_alias_declaration":
            # Find the = sign and return everything before
            if "=" in self.src_code:
                return self.src_code.split("=")[0].strip()
        
        # Fall back to JavaScript signature extraction
        return super().signature

    @property
    def stub(self) -> str:
        """
        Generate stub code for TypeScript entity.
        
        Handles TypeScript-specific declarations.
        """
        signature = self.signature
        
        if self.node.type == "interface_declaration":
            return f"{signature} {{\n\t// TODO: Define interface members\n}}"
        elif self.node.type == "enum_declaration":
            return f"{signature} {{\n\t// TODO: Define enum values\n}}"
        elif self.node.type == "type_alias_declaration":
            return f"{signature} = unknown; // TODO: Define type"
        
        # Fall back to JavaScript stub generation
        return super().stub


def get_entities_from_file_ts(
    entities: list[TypeScriptEntity],
    file_path: str,
    max_entities: int = -1,
) -> list[TypeScriptEntity]:
    """
    Parse a .ts/.tsx file and return up to max_entities top-level entities.
    
    This function parses TypeScript/TSX files using tree-sitter-typescript
    and extracts functions, classes, interfaces, type aliases, and enums.
    
    Args:
        entities: List to append extracted entities to
        file_path: Path to the TypeScript file
        max_entities: Maximum number of entities to collect (-1 for all)
    
    Returns:
        Updated list of entities
    """
    # Choose parser based on file extension
    if file_path.endswith(".tsx"):
        parser = Parser(TSX_LANGUAGE)
    else:
        parser = Parser(TS_LANGUAGE)

    try:
        file_content = open(file_path, "r", encoding="utf8").read()
    except UnicodeDecodeError:
        warnings.warn(f"Could not decode file {file_path}", stacklevel=2)
        return entities

    tree = parser.parse(bytes(file_content, "utf8"))
    root = tree.root_node
    lines = file_content.splitlines()

    _walk_and_collect_ts(root, entities, lines, str(file_path), max_entities)
    return entities


def _walk_and_collect_ts(node, entities, lines, file_path, max_entities):
    """
    Walk the TypeScript AST and collect entities.
    
    Strictly aligned with Python's python.py which only collects ClassDef and FunctionDef.
    We only collect executable code entities that can have logical bugs introduced:
    
    Collects:
    - function_declaration (equivalent to Python FunctionDef)
    - method_definition (equivalent to Python FunctionDef in class)
    - class_declaration (equivalent to Python ClassDef)
    - Variable declarations containing function expressions
    - Assignment expressions with function values
    
    NOT collected (pure type definitions without executable code):
    - interface_declaration: TypeScript-only type definition, no runtime code
    - type_alias_declaration: TypeScript-only type alias, no runtime code
    - enum_declaration: While enums have runtime values, they typically don't contain
                        modifiable logic that can introduce bugs
    """
    # Stop if we've hit the limit
    if 0 <= max_entities == len(entities):
        return

    if node.type == "ERROR":
        warnings.warn(f"Error encountered parsing {file_path}", stacklevel=2)
        return

    # Collect only executable code entities (aligned with Python's ClassDef/FunctionDef)
    # Removed: interface_declaration, type_alias_declaration, enum_declaration
    # These are pure type definitions that cannot have logical bugs introduced
    if node.type in [
        "function_declaration",
        "method_definition",
        "class_declaration",
    ]:
        entities.append(
            build_entity(
                node, lines, file_path, TypeScriptEntity, default_indent_size=2
            )
        )
        if 0 <= max_entities == len(entities):
            return

    # Also collect variable declarations that contain function expressions
    elif node.type in ["variable_declaration", "lexical_declaration"]:
        _collect_variable_functions_ts(node, entities, lines, file_path, max_entities)

    # Collect assignment expressions with function values
    elif node.type == "assignment_expression":
        _collect_assignment_functions_ts(node, entities, lines, file_path, max_entities)

    for child in node.children:
        _walk_and_collect_ts(child, entities, lines, file_path, max_entities)


def _collect_variable_functions_ts(node, entities, lines, file_path, max_entities):
    """
    Collect function expressions from variable declarations.
    
    Handles both `var/let/const myFunc = function() {}` and arrow functions.
    """
    for child in node.children:
        if child.type == "variable_declarator":
            for grandchild in child.children:
                if grandchild.type in ["function_expression", "arrow_function"]:
                    entities.append(
                        build_entity(
                            child,
                            lines,
                            file_path,
                            TypeScriptEntity,
                            default_indent_size=2,
                        )
                    )
                    if 0 <= max_entities == len(entities):
                        return


def _collect_assignment_functions_ts(node, entities, lines, file_path, max_entities):
    """
    Collect function expressions from assignment expressions.
    
    Handles cases like `module.exports.myFunc = function() {}`.
    """
    for child in node.children:
        if child.type in ["function_expression", "arrow_function"]:
            entities.append(
                build_entity(
                    node, lines, file_path, TypeScriptEntity, default_indent_size=2
                )
            )
            if 0 <= max_entities == len(entities):
                return
