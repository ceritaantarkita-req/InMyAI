# InMyAI

**Small models. Right context. Real local work.**

InMyAI is a lightweight, local-first AI workspace designed for everyday laptops with **8–16 GB RAM**. It routes each task to the most suitable local model or deterministic tool, preserves project context across sessions, and works with local files through controlled permissions.

> InMyAI is not a new foundation model and it is not an Ollama clone. Gemma, Nemotron, Qwen, Phi, and other local models provide intelligence; Ollama or llama.cpp runs the model; InMyAI provides memory, context retrieval, tools, permissions, routing, verification, and the product experience.

## Repository description

> A lightweight, local-first AI workspace with automatic model routing, persistent project memory, knowledge graphs, controlled file tools, OCR, coding assistance, and optional local image generation—designed for everyday 8–16 GB laptops.

## Working P0 capabilities

- Next.js workspace UI with eight primary surfaces: Chat, Files, Memory, Graph, Studio, Git, Agents, Explorer
- Explorer: a mind-map style folder/file browser (`GET /api/browse`) for finding a project across your whole disk before registering it - browsing names never requires an allowed root, only opening a folder as a chat project does
- A second, dependency-free UI (`apps/local-ui`, no Node/npm needed) served by the API itself at `/app/`
- FastAPI local backend and SQLite/FTS5 persistence
- Register and incrementally index explicitly allowed local folders
- Text/code, PDF, DOCX, XLSX, and PPTX parsing
- Search indexed code and documents with SQLite FTS5/BM25
- AST-based code relation graph (tree-sitter: Python, JS/TS, Go, Rust, PHP, Java, C, C++)
- Read-only Git surface: status, log, diff, branches, blame
- Automatic task classification and model/tool routing
- Automatic selection among installed Ollama models by task and model size
- Safe mock provider, allowing the whole core to run without downloading model weights
- Ollama local chat provider
- Multi-agent task orchestration (Coordinator/Researcher/Worker/Verifier) with durable, replayable checkpoints — see `docs/agent-runtime.md`
- First-run onboarding wizard that detects Ollama's install/running/model state and guides setup
- Persistent project memory and structured decision ledger
- Active/superseded decision handling
- File editing through proposal → diff → approval → backup → write, with stale-write detection and atomic writes
- PDF text extraction and real local Tesseract OCR
- Low-memory image workflow simulator for testing
- Optional real local image generation through Diffusers or ComfyUI integration
- Hardware/resource monitor and 1.5 GB available-RAM safety guard
- One-heavy-engine-at-a-time architecture
- English-first interface with straightforward i18n extension path

## Quick start — Windows

Requirements:

- Node.js 22+
- Python 3.11–3.13
- Optional: Ollama
- Optional OCR: Tesseract OCR

```powershell
Copy-Item .env.example .env
npm run setup
npm run dev
```

Open:

- Web: `http://127.0.0.1:3000`
- API docs: `http://127.0.0.1:8000/docs`

Seed the included safe demo project:

```powershell
.venv\Scripts\python.exe scripts\seed_demo.py
```

Then click the refresh/index button in the UI.

## Quick start — Linux/macOS

```bash
cp .env.example .env
npm run setup
npm run dev
```

Seed demo data:

```bash
.venv/bin/python scripts/seed_demo.py
```

## Using Ollama

The Workspace UI shows a setup wizard automatically the first time it detects Ollama is missing, not running, or has no model pulled yet — it walks through download → start → pull a recommended model, with each step re-checked on demand. It re-opens any time from **Settings → Set up Ollama**, and can be dismissed ("Remind me later") without blocking the rest of the app, which keeps running in Safe Mock mode.

To do the same steps manually: install Ollama separately, download a model that fits the device, then start Ollama. Example model choices:

- 8 GB RAM: 1B–2B Q4 class
- 16 GB RAM: 3B–4B Q4 class

Set `.env`:

```env
INMYAI_PROVIDER=ollama
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_MODEL=gemma3:4b
```

In **Automatic router** mode, InMyAI examines the task and installed Ollama models. Coding tasks prefer a small model with `coder`/`code` in its name; general, graph, and memory explanation tasks prefer suitable general models. The smallest matching installed model is selected first.

## Safe local file access

Default access is limited to `./workspace`. Add explicit roots with the operating system path separator:

```env
# Windows
INMYAI_ALLOWED_ROOTS=C:\dev;D:\work

# Linux/macOS
INMYAI_ALLOWED_ROOTS=/home/me/projects:/mnt/work
```

Sensitive paths and common credential files are blocked. Setting `INMYAI_ALLOW_ANY_LOCAL_PATH=true` is possible but not recommended.

## Quality checks

```bash
npm run qa
```

The command runs:

- strict TypeScript check
- frontend tests
- FastAPI tests
- Next.js production build

## What is intentionally not bundled

- model weights
- personal project data
- private memories or conversations
- production secrets
- a bundled image diffusion model
- Graphify output from a user's private project

These belong on the user's local device and are excluded by `.gitignore`.

## Documentation

Start with:

- [`docs/prd.md`](docs/prd.md)
- [`docs/architecture.md`](docs/architecture.md)
- [`docs/memory-system.md`](docs/memory-system.md)
- [`docs/model-routing.md`](docs/model-routing.md)
- [`docs/github-repository.md`](docs/github-repository.md)
- [`docs/security.md`](docs/security.md)
- [`docs/testing-qa.md`](docs/testing-qa.md)
- [`docs/limitations.md`](docs/limitations.md)

## License

Apache-2.0 for the application source. Model weights remain subject to each model provider's license.
