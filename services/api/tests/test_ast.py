from __future__ import annotations

from services.api.app.ast_extractor import (
    extract_relations_ast,
    language_for_suffix,
)


# Helper: relations returned as a set of (relation, target) for easy asserting,
# ignoring evidence/confidence which are tested separately where relevant.
def rel_pairs(rows):
    return {(r[0], r[1]) for r in rows}


# ---------- language dispatch ----------

def test_language_for_suffix_maps_known_languages() -> None:
    assert language_for_suffix('.py') == 'python'
    assert language_for_suffix('.js') == 'javascript'
    assert language_for_suffix('.jsx') == 'javascript'
    assert language_for_suffix('.ts') == 'typescript'
    assert language_for_suffix('.tsx') == 'tsx'


def test_language_for_suffix_returns_none_for_unsupported() -> None:
    assert language_for_suffix('.go') is None
    assert language_for_suffix('.json') is None
    assert language_for_suffix('.md') is None
    assert language_for_suffix('') is None


# ---------- Python imports & defines ----------

def test_python_extracts_imports() -> None:
    rows = extract_relations_ast(
        'src/app.py',
        'import os\nimport json as j\nfrom foo.bar import baz\n',
        'python',
    )
    pairs = rel_pairs(rows)
    assert ('imports', 'os') in pairs
    assert ('imports', 'foo.bar') in pairs


def test_python_extracts_definitions() -> None:
    rows = extract_relations_ast(
        'src/app.py',
        'def my_func():\n    pass\n\nclass MyClass:\n    pass\n',
        'python',
    )
    pairs = rel_pairs(rows)
    assert ('defines', 'my_func') in pairs
    assert ('defines', 'MyClass') in pairs


def test_python_extracts_calls() -> None:
    rows = extract_relations_ast(
        'src/app.py',
        'def f():\n    print("hi")\n    do_thing()\n',
        'python',
    )
    pairs = rel_pairs(rows)
    assert ('calls', 'print') in pairs
    assert ('calls', 'do_thing') in pairs


# ---------- JavaScript imports & defines ----------

def test_javascript_extracts_imports_with_string_specifier() -> None:
    rows = extract_relations_ast(
        'src/app.js',
        "import { x } from './mod'\nimport defaults from 'lib'\n",
        'javascript',
    )
    pairs = rel_pairs(rows)
    assert ('imports', './mod') in pairs
    assert ('imports', 'lib') in pairs


def test_javascript_extracts_function_definitions() -> None:
    rows = extract_relations_ast(
        'src/app.js',
        'export function myFunc() { return 1 }\nfunction helper() {}\n',
        'javascript',
    )
    pairs = rel_pairs(rows)
    assert ('defines', 'myFunc') in pairs
    assert ('defines', 'helper') in pairs


# ---------- TypeScript interfaces & types ----------

def test_typescript_extracts_interface_and_type_definitions() -> None:
    rows = extract_relations_ast(
        'src/types.ts',
        'export interface Foo {}\nexport type Bar = string\nexport function baz() {}\n',
        'typescript',
    )
    pairs = rel_pairs(rows)
    assert ('defines', 'Foo') in pairs
    assert ('defines', 'Bar') in pairs
    assert ('defines', 'baz') in pairs


def test_typescript_extracts_imports() -> None:
    rows = extract_relations_ast(
        'src/types.ts',
        "import { z } from 'lib'\nimport thing from './local'\n",
        'typescript',
    )
    pairs = rel_pairs(rows)
    assert ('imports', 'lib') in pairs
    assert ('imports', './local') in pairs


# ---------- TSX (React component) ----------

def test_tsx_extracts_component_definitions_and_imports() -> None:
    rows = extract_relations_ast(
        'src/Card.tsx',
        "import React from 'react'\nexport function Card() { return null }\n",
        'tsx',
    )
    pairs = rel_pairs(rows)
    assert ('imports', 'react') in pairs
    assert ('defines', 'Card') in pairs


# ---------- Robustness ----------

def test_unsupported_language_returns_empty() -> None:
    # extract_relations_ast takes an explicit language string; unsupported langs
    # (mapped via language_for_suffix before this call, but the extractor must
    # also be defensive) return [].
    assert extract_relations_ast('app.go', 'package main\n', 'go') == []


def test_syntax_error_returns_empty_without_raising() -> None:
    # Malformed Python must not crash the indexer.
    rows = extract_relations_ast('broken.py', 'def (((\n', 'python')
    assert isinstance(rows, list)


def test_empty_content_returns_empty() -> None:
    assert extract_relations_ast('empty.py', '', 'python') == []


def test_relations_carry_evidence_and_extracted_confidence() -> None:
    rows = extract_relations_ast('app.py', 'import os\n', 'python')
    assert rows, 'expected at least one row'
    relation, target, evidence, confidence = rows[0]
    assert confidence == 'EXTRACTED'
    assert 'import' in evidence  # evidence contains the source snippet
