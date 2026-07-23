# Roadmap

## P0 — included

Core local workspace, project indexing, FTS5 retrieval, memory, decision ledger, built-in graph, Safe Mock, Ollama adapter, controlled writes, OCR, resource guard, and optional image plugin scaffold.

## P1

- Tauri desktop shell and native folder picker
- ~~Graphify importer~~ ✓ implemented (CLI: `scripts/import_graphify.py`)
- ~~Git tools~~ ✓ implemented (`git_tools.py`: read-only status/log/diff/branch/blame)
- language-server
- ~~mind-map folder/file browser~~ ✓ implemented (`GET /api/browse` + `Workspace.tsx`: `ExplorerView`, radial mind-map, drill-down to file level, no allowed-roots gate on browsing names — see `docs/decisions/explorer-and-terminal.md`)
- ~~real interactive terminal~~ ✓ implemented (`/ws/terminal` PTY relay + `Workspace.tsx`/`TerminalView.tsx`, xterm.js); intentionally **not sandboxed** — full shell access under your own account, see `docs/decisions/explorer-and-terminal.md`
- terminal approval sandbox — a distinct, still-unbuilt future item: a *restricted*, approval-gated command runner, as opposed to the raw interactive terminal above
- ~~model benchmark registry~~ ✓ implemented (`models/registry.json` + `model_registry.py`); shipped profiles are `verified: false` pending user benchmarks
- model load/unload lifecycle hooks
- semantic embedding plugin
- ~~DOCX/XLSX/PPTX parsers~~ ✓ implemented (`indexer.py`, ported from v2 during the v1/v2 merge)
- ~~multi-agent task orchestration~~ ✓ implemented (`agent_runtime.py`: Coordinator/Researcher/Worker/Verifier, ported from v2 during the v1/v2 merge), see `docs/agent-runtime.md`
- ~~dependency-free fallback UI~~ ✓ implemented (`apps/local-ui`, served at `/app/`, ported from v2); kept permanently as a lightweight fallback surface, see `docs/decisions/v1-v2-merge-and-agents-panel.md`
- ~~stale-write detection on file proposals~~ ✓ implemented (`services.py`: sha256 check + atomic tempfile write, ported from v2)
- Indonesian localization
- ComfyUI executor
- AST-based graph extraction (tree-sitter for Python/JS/TS, replacing regex) ✓ implemented (`ast_extractor.py`); expanded to Go/Rust/PHP/Java/C/C++
- ~~Agents tab in the Next.js Workspace UI~~ ✓ implemented (`Workspace.tsx`: `AgentsView`, agent roster + task queue + live checkpoint timeline)
- ~~INMYAI_* env-prefix binding bug~~ ✓ fixed (`config.py`: `env_prefix='INMYAI_'` + per-field `validation_alias` for the intentionally-unprefixed Ollama/ComfyUI vars); documented env vars now actually bind

## P2

- plugin marketplace
- local voice
- multi-project graph
- evaluation/dataset lab
- LoRA workflow
- local network worker nodes
