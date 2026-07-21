# Architecture

```text
Next.js UI
   │ HTTP localhost
   ▼
FastAPI local service
   ├── project/file permission layer
   ├── incremental indexer
   ├── task classifier and model router
   ├── context compiler
   ├── memory and decision service
   ├── graph service
   ├── write proposal/backup service
   ├── OCR service
   └── image backend adapter
          │
          ├── Safe Mock
          ├── Ollama
          ├── Tesseract / pypdf
          ├── optional ComfyUI
          └── optional Diffusers

SQLite WAL + FTS5
Local project folders
Optional graph.json / model runtimes
```

## Why Next.js + FastAPI

Next.js owns the interactive workspace and responsive product UI. FastAPI owns Python-native indexing, OCR, graph processing, local model adapters, background work, and filesystem policy.

## Core storage

SQLite tables:

- projects
- files
- files_fts
- memories
- decisions
- relations
- conversations
- messages
- write_proposals
- tasks
- audit_log

## Incremental indexing

The indexer hashes supported files and only reprocesses changed files. It ignores dependency/build/model folders and files larger than the configured limit.

## Runtime policy

P0 provides route decisions and RAM guard. Full production lifecycle hooks for unloading Ollama/ComfyUI models are P1 because runtimes expose different unload semantics.

## Failure strategy

- Ollama unavailable → Safe Mock
- OCR runtime unavailable → explicit error with setup documentation
- insufficient available RAM → block new heavy engine
- invalid/sensitive path → reject before reading
- write conflict → staged diff remains pending
