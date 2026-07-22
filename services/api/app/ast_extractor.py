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

import tree_sitter_javascript as tsjs
import tree_sitter_python as tspython
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


def _extract_jsts_imports(node: Node, source: bytes) -> list[_RELATION_TUPLE]:
    """For a JS/TS import_statement, return an 'imports' row per source string.

    E.g. `import {a, b} from 'mod'` → one row target='mod'.
    Side-effect imports like `import 'side-effect.css'` also match.
    """
    rows: list[_RELATION_TUPLE] = []
    for child in _walk(node):
        if child.type == 'string':
            spec = _strip_quotes(_node_text(child, source))
            if spec:
                rows.append(('imports', spec, _evidence_for(node, source), 'EXTRACTED'))
    return rows


def _extract_python_imports(node: Node, source: bytes) -> list[_RELATION_TUPLE]:
    """For a Python import_statement / import_from_statement, return imports rows.

    `import os` → 'os'
    `import os.path` → 'os.path'
    `from foo.bar import baz` → 'foo.bar'
    """
    rows: list[_RELATION_TUPLE] = []
    if node.type == 'import_from_statement':
        # module is the dotted_name right after `from`
        for child in node.named_children:
            if child.type == 'dotted_name':
                rows.append(('imports', _node_text(child, source), _evidence_for(node, source), 'EXTRACTED'))
                break
    elif node.type == 'import_statement':
        # one or more dotted names; `import a, b` → both
        for child in node.named_children:
            if child.type == 'dotted_name':
                rows.append(('imports', _node_text(child, source), _evidence_for(node, source), 'EXTRACTED'))
            elif child.type == 'aliased_import':
                # `import x as y` — the inner dotted_name is the real module
                for inner in child.named_children:
                    if inner.type == 'dotted_name':
                        rows.append(('imports', _node_text(inner, source), _evidence_for(node, source), 'EXTRACTED'))
    return rows


_DEFINE_NODE_TYPES = {
    'function_declaration',       # JS/TS
    'class_declaration',          # JS/TS
    'interface_declaration',      # TS
    'type_alias_declaration',     # TS
    'function_definition',        # Python
    'class_definition',           # Python
}


def _definition_name(node: Node, source: bytes) -> str | None:
    """The declared identifier of a definition node, or None."""
    for child in node.named_children:
        if child.type in ('identifier', 'type_identifier'):
            return _node_text(child, source)
    return None


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

    is_python = language == 'python'
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
        if is_python and node.type in ('import_statement', 'import_from_statement'):
            for relation, target, evidence, confidence in _extract_python_imports(node, source):
                add(relation, target, evidence)
        elif not is_python and node.type == 'import_statement':
            for relation, target, evidence, confidence in _extract_jsts_imports(node, source):
                add(relation, target, evidence)
        elif node.type in _DEFINE_NODE_TYPES:
            name = _definition_name(node, source)
            if name:
                add('defines', name, _evidence_for(node, source))
        elif node.type in ('call_expression', 'call'):
            callee = _callee_name(node, source)
            if callee:
                add('calls', callee, _evidence_for(node, source))

    return rows
