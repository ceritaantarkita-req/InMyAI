"""Tree-sitter based AST relation extraction.

Replaces the old regex-based `_extract_relations` in the indexer. Parses Python,
JavaScript, and TypeScript/TSX into a real syntax tree and extracts:
  - imports (module specifiers)
  - defines (functions, classes, interfaces, types)
  - calls (called identifiers)

Returns rows shaped (relation, target_node, evidence, confidence) — the indexer
prepends project_id and source_node when inserting into the relations table.
The `confidence` is always the string literal 'EXTRACTED'.

Unsupported languages and unparseable files return [] — indexing must never
crash on a single bad file.
"""
from __future__ import annotations

from typing import Iterable

import tree_sitter_c as tsc
import tree_sitter_cpp as tscpp
import tree_sitter_go as tsgo
import tree_sitter_javascript as tsjs
import tree_sitter_java as tsjava
import tree_sitter_php as tsphp
import tree_sitter_python as tspython
import tree_sitter_rust as tsrust
import tree_sitter_typescript as tsts
from tree_sitter import Language, Node, Parser


_RELATION_TUPLE = tuple  # (relation, target_node, evidence, confidence)


def language_for_suffix(suffix: str) -> str | None:
    """Map a file extension to a tree-sitter language name, or None if unsupported."""
    mapping = {
        '.py': 'python',
        '.js': 'javascript',
        '.jsx': 'javascript',
        '.ts': 'typescript',
        '.tsx': 'tsx',
        '.go': 'go',
        '.rs': 'rust',
        '.php': 'php',
        '.java': 'java',
        '.c': 'c',
        '.h': 'c',
        '.cpp': 'cpp',
        '.cc': 'cpp',
        '.cxx': 'cpp',
        '.hpp': 'cpp',
    }
    return mapping.get(suffix.lower())


# Parsers are built once per language (grammar load is the expensive part) and
# reused. tree-sitter parsers are not thread-safe, but InMyAI is single-process
# and indexing runs single-threaded per project.
_PARSERS: dict[str, Parser] = {}


def _parser_for(language: str) -> Parser | None:
    if language in _PARSERS:
        return _PARSERS[language]
    lang_obj = _LANGUAGE_OBJECTS.get(language)
    if lang_obj is None:
        return None
    parser = Parser(lang_obj)
    _PARSERS[language] = parser
    return parser


_LANGUAGE_OBJECTS: dict[str, Language] = {}


def _build_language_objects() -> None:
    if _LANGUAGE_OBJECTS:
        return
    _LANGUAGE_OBJECTS['python'] = Language(tspython.language())
    _LANGUAGE_OBJECTS['javascript'] = Language(tsjs.language())
    _LANGUAGE_OBJECTS['typescript'] = Language(tsts.language_typescript())
    _LANGUAGE_OBJECTS['tsx'] = Language(tsts.language_tsx())
    _LANGUAGE_OBJECTS['go'] = Language(tsgo.language())
    _LANGUAGE_OBJECTS['rust'] = Language(tsrust.language())
    _LANGUAGE_OBJECTS['php'] = Language(tsphp.language_php_only())
    _LANGUAGE_OBJECTS['java'] = Language(tsjava.language())
    _LANGUAGE_OBJECTS['c'] = Language(tsc.language())
    _LANGUAGE_OBJECTS['cpp'] = Language(tscpp.language())


_build_language_objects()


def _node_text(node: Node, source: bytes) -> str:
    """Decode a node's byte range from the source, safely."""
    return source[node.start_byte:node.end_byte].decode('utf-8', errors='replace')


def _evidence_for(node: Node, source: bytes) -> str:
    """Source snippet of the line where the node starts, capped at 300 chars."""
    line_start = node.start_byte
    # Walk back to the previous newline for a readable line-based excerpt.
    while line_start > 0 and source[line_start - 1:line_start] not in (b'\n', b'\r'):
        line_start -= 1
    snippet = source[line_start:node.end_byte].decode('utf-8', errors='replace').strip()
    return snippet[:300]


def _strip_quotes(text: str) -> str:
    """Remove surrounding quotes from a module specifier string node text."""
    if len(text) >= 2 and text[0] in '\'"`' and text[-1] == text[0]:
        return text[1:-1]
    return text


def _walk(node: Node) -> Iterable[Node]:
    """Yield a node and all its descendants, depth-first."""
    stack = [node]
    while stack:
        current = stack.pop()
        yield current
        # push reversed so children are visited in source order
        for child in reversed(current.children):
            stack.append(child)


_DEFINE_NODE_TYPES = {
    'function_declaration',       # JS/TS/Go
    'class_declaration',          # JS/TS/PHP/Java
    'interface_declaration',      # TS
    'type_alias_declaration',     # TS
    'type_declaration',           # Go (wraps type_spec)
    'function_definition',        # Python/C/C/PHP
    'class_definition',           # Python
    'function_item',              # Rust
    'struct_item',                # Rust
    'type_definition',            # C/C typedef
    'class_specifier',            # C++
    'method_declaration',         # Java
}


# Node types whose subtree may carry the declaration's name identifier.
# 'name' is used by the PHP grammar; 'identifier'/'type_identifier' by most others.
_NAME_LEAF_TYPES = ('identifier', 'type_identifier', 'name')


def _definition_name(node: Node, source: bytes) -> str | None:
    """The declared identifier of a definition node, or None.

    Handles the common case (direct identifier/type_identifier child) plus the
    C/C `function_declarator` wrapper and Go's `type_spec`.
    """
    # Go: type_declaration wraps one or more type_spec nodes.
    if node.type == 'type_declaration':
        for child in node.named_children:
            if child.type == 'type_spec':
                for leaf in child.named_children:
                    if leaf.type == 'type_identifier':
                        return _node_text(leaf, source)
        return None
    # Direct identifier child (covers JS/TS/Java/PHP/Rust struct/function).
    for child in node.named_children:
        if child.type in _NAME_LEAF_TYPES:
            return _node_text(child, source)
    # C/C: function_definition → function_declarator → identifier
    if node.type == 'function_definition':
        for child in node.named_children:
            if child.type == 'function_declarator':
                for leaf in child.named_children:
                    if leaf.type == 'identifier':
                        return _node_text(leaf, source)
    return None


# ---- per-language import target extraction ----

_IMPORT_NODE_TYPES = {
    'import_statement',           # JS/TS/Python
    'import_from_statement',      # Python
    'import_declaration',         # Go/Java
    'use_declaration',            # Rust
    'namespace_use_declaration',  # PHP
    'preproc_include',            # C/C++
}


def _import_target(node: Node, language: str, source: bytes) -> list[str]:
    """Return one or more module/path targets for an import node, per language."""
    targets: list[str] = []

    if language in ('javascript', 'typescript', 'tsx'):
        for child in _walk(node):
            if child.type == 'string':
                spec = _strip_quotes(_node_text(child, source))
                if spec:
                    targets.append(spec)
        return targets

    if language == 'python':
        if node.type == 'import_from_statement':
            for child in node.named_children:
                if child.type == 'dotted_name':
                    targets.append(_node_text(child, source))
                    break
        else:  # import_statement
            for child in node.named_children:
                if child.type == 'dotted_name':
                    targets.append(_node_text(child, source))
                elif child.type == 'aliased_import':
                    for inner in child.named_children:
                        if inner.type == 'dotted_name':
                            targets.append(_node_text(inner, source))
        return targets

    if language == 'go':
        # import_declaration → import_spec(s) → interpreted_string_literal
        for child in _walk(node):
            if child.type == 'interpreted_string_literal':
                spec = _strip_quotes(_node_text(child, source))
                if spec:
                    targets.append(spec)
        return targets

    if language == 'java':
        # import_declaration → scoped_identifier (full path)
        for child in node.named_children:
            if child.type in ('scoped_identifier', 'identifier'):
                targets.append(_node_text(child, source))
        return targets

    if language == 'rust':
        # use_declaration → scoped_identifier (std::io) or identifier
        for child in node.named_children:
            if child.type in ('scoped_identifier', 'identifier'):
                targets.append(_node_text(child, source))
        return targets

    if language == 'php':
        # namespace_use_declaration → namespace_use_clause → qualified_name
        for child in _walk(node):
            if child.type == 'qualified_name':
                targets.append(_node_text(child, source))
        return targets

    if language in ('c', 'cpp'):
        # preproc_include → system_lib_string (<stdio.h>) or string_literal ("x.h")
        for child in node.named_children:
            text = _node_text(child, source)
            if child.type == 'system_lib_string':
                targets.append(text.strip('<>'))
            elif child.type == 'string_literal':
                stripped = _strip_quotes(text)
                if stripped:
                    targets.append(stripped)
        return targets

    return targets


def _callee_name(node: Node, source: bytes) -> str | None:
    """The called identifier of a call_expression, or None.

    Only simple name calls are extracted (e.g. `foo()`, `obj.method()`).
    Calls like `(factory())()` or template-literal calls are skipped.
    """
    callee = node.child_by_field_name('function')
    if callee is None:
        # Python grammar exposes the callee as the first named child.
        named = node.named_children
        callee = named[0] if named else None
    if callee is None:
        return None
    if callee.type == 'identifier':
        return _node_text(callee, source)
    if callee.type == 'member_expression':
        # `obj.method` → keep 'obj.method' so the graph still links the symbol
        return _node_text(callee, source)
    return None


def extract_relations_ast(relative: str, content: str, language: str) -> list[_RELATION_TUPLE]:
    """Parse `content` as `language` and return relation rows.

    Rows are shaped (relation, target_node, evidence, confidence). The indexer
    prepends project_id and source_node (= `relative`) when inserting.

    Returns [] for unsupported languages or unparseable input — never raises.
    """
    parser = _parser_for(language)
    if parser is None:
        return []
    source = content.encode('utf-8', errors='replace')
    try:
        tree = parser.parse(source)
    except Exception:
        return []
    if tree.root_node is None:
        return []

    is_jsts = language in ('javascript', 'typescript', 'tsx')
    rows: list[_RELATION_TUPLE] = []
    seen: set[tuple[str, str]] = set()

    def add(relation: str, target: str, evidence: str) -> None:
        if not target:
            return
        key = (relation, target)
        if key in seen:
            return
        seen.add(key)
        rows.append((relation, target, evidence, 'EXTRACTED'))

    for node in _walk(tree.root_node):
        if node.type in _IMPORT_NODE_TYPES:
            evidence = _evidence_for(node, source)
            for target in _import_target(node, language, source):
                add('imports', target, evidence)
        elif node.type in _DEFINE_NODE_TYPES:
            name = _definition_name(node, source)
            if name:
                add('defines', name, _evidence_for(node, source))
        elif is_jsts and node.type in ('call_expression',):
            callee = _callee_name(node, source)
            if callee:
                add('calls', callee, _evidence_for(node, source))
        elif language == 'python' and node.type == 'call':
            callee = _callee_name(node, source)
            if callee:
                add('calls', callee, _evidence_for(node, source))

    return rows
