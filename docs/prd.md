# InMyAI Product Requirements Document

## Product vision

InMyAI is a local-first AI workspace that makes small local models useful for real project work on laptops with 8–16 GB RAM. It preserves context outside the model, routes work to specialized engines, and grants controlled access to local files.

## Problem

Current AI tools frequently lose project context, mix old and current decisions, require repeated document loading, or assume expensive hardware. A long `prd.md` or append-only `log.md` remains passive unless the system retrieves, resolves, and compiles the right information at execution time.

## Primary users

- developers using consumer Windows laptops
- researchers and analysts working with private documents
- Indonesian SMEs that cannot send project data to cloud services
- students and independent creators
- open-source contributors building local AI workflows

## Hard constraints

- minimum target: 8 GB RAM
- recommended target: 16 GB RAM
- GPU optional
- one heavy engine active at a time
- core works without cloud API keys
- model weights are never committed to the repository
- local file writes require explicit approval
- decisions must support active and superseded states
- no claim that a small model equals a large cloud model

## P0 user journeys

### Add and understand a project

1. User registers an allowed local folder.
2. InMyAI validates the path against policy.
3. Incremental indexer reads supported text/code/PDF files.
4. FTS5 and relation graph are updated.
5. User asks a question.
6. Context compiler retrieves active decisions, memories, and relevant source excerpts.
7. Router chooses a deterministic tool, Safe Mock, or Ollama.
8. Answer shows source files and routing reason.

### Safely edit a file

1. User opens an indexed file.
2. User or AI proposes new content.
3. InMyAI creates a unified diff.
4. User explicitly approves or rejects.
5. On approval, InMyAI creates a timestamped backup.
6. File is written and audit log updated.
7. Project can be re-indexed.

### Preserve a decision

1. User records a decision.
2. Optionally selects an older decision it replaces.
3. Old decision becomes `superseded`.
4. New decision becomes `active`.
5. Context compiler prefers active decisions.

### OCR

1. User selects an indexed image or PDF.
2. PDF text uses pypdf.
3. Image text uses local Tesseract.
4. Output is shown and can later be stored as an artifact/memory.

### Image workflow

1. User writes a prompt.
2. Core simulator verifies job, file, artifact, and UI flow without pretending it is AI output.
3. User can optionally enable a real ComfyUI or Diffusers backend.
4. Chat model must be unloaded before a heavy image model is loaded in the production lifecycle manager.

## Functional requirements

- project registration and indexing
- local full-text search
- project chat with citations
- automatic route explanation
- Ollama model discovery and task-based selection
- memory CRUD
- decision ledger with supersession
- graph query
- file read and staged write
- automatic backup
- OCR
- optional image generation plugin
- hardware snapshot
- low-memory guard
- responsive Next.js interface
- public GitHub repository hygiene

## Non-functional requirements

- strict TypeScript
- Python type-friendly structure
- SQLite WAL mode
- no secrets in Git
- safe failure when Ollama is unavailable
- deterministic test provider
- accessible keyboard controls
- responsive desktop/mobile layout
- documented limitations

## P1

- native Tauri shell and folder picker
- language-server integration
- git patch and commit tools
- Graphify `graph.json` importer
- semantic embedding plugin
- model lifecycle manager with unload hooks
- task handoff snapshots
- structured artifacts and OCR export
- ComfyUI workflow editor
- Indonesian localization

## P2

- plugin marketplace
- multi-project relationship graph
- local voice input/output
- remote worker node on a second local PC
- LoRA dataset/evaluation workflow
- distributed optional inference
