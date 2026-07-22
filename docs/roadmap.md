# Roadmap

## P0 — included

Core local workspace, project indexing, FTS5 retrieval, memory, decision ledger, built-in graph, Safe Mock, Ollama adapter, controlled writes, OCR, resource guard, and optional image plugin scaffold.

## P1

- Tauri desktop shell and native folder picker
- ~~Graphify importer~~ ✓ implemented (CLI: `scripts/import_graphify.py`)
- language-server and Git tools
- terminal approval sandbox
- ~~model benchmark registry~~ ✓ implemented (`models/registry.json` + `model_registry.py`); shipped profiles are `verified: false` pending user benchmarks
- model load/unload lifecycle hooks
- semantic embedding plugin
- DOCX/XLSX parsers
- Indonesian localization
- ComfyUI executor
- AST-based graph extraction (tree-sitter for Python/JS/TS, replacing regex) ✓ implemented (`ast_extractor.py`)

## P2

- plugin marketplace
- local voice
- multi-project graph
- evaluation/dataset lab
- LoRA workflow
- local network worker nodes
