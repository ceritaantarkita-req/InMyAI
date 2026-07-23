# Technical Specification

## Versions

- Node.js 22+
- Next.js 16.2.10
- React 19.2.7
- TypeScript 5.8.3
- Python 3.11–3.13
- FastAPI 0.116.1
- SQLite with FTS5

## Web app

Path: `apps/web`

- App Router
- strict TypeScript
- native CSS design system
- no heavyweight component framework
- localhost API client

## API

Path: `services/api`

Primary endpoints:

- `GET /api/health`
- `GET /api/hardware`
- `GET /api/models/status`
- `GET|POST /api/projects`
- `POST /api/projects/{id}/index`
- `GET /api/projects/{id}/files`
- `GET /api/projects/{id}/file`
- `POST /api/search`
- `POST /api/chat`
- memory and decision endpoints
- graph endpoints
- proposal/apply/reject endpoints
- `POST /api/ocr`
- `POST /api/images/generate`
- `GET /api/projects/{id}/git/{status,log,branches,diff,blame}` (read-only)

## Supported indexing formats

- code/text: MD, TXT, JSON, YAML, TOML, INI, Python, JS/TS, CSS, HTML, SQL, shell, PowerShell, Go, Rust, Java, C/C++, C#, PHP, Ruby, Swift, Kotlin
- PDFs with extractable text
- Office: DOCX (python-docx), XLSX (openpyxl) — extracted into the same FTS5 index

The direct-read size limit defaults to 8 MB (INMYAI_MAX_FILE_MB), raised from
2 MB so typical office documents are not silently excluded.

## Search

SQLite FTS5 with BM25 ordering. The query is tokenized and safely quoted before use in `MATCH`.

## Graph

Relations are extracted from real syntax trees via tree-sitter for:
Python, JavaScript/JSX, TypeScript/TSX, Go, Rust, PHP, Java, C, and C++.

For each file the extractor records:

- imports (module specifiers / `#include` / `use` / `import`)
- definitions (functions, classes, interfaces, types, structs)
- calls (JS/TS/Python only)

Languages without a grammar (Ruby, Swift, Kotlin, C#, Markdown, JSON, ...)
produce no relation rows rather than pseudo-relations from fragile regex.

Every built-in edge is tagged `EXTRACTED`. Graphify edges are tagged
`INFERRED` (see `scripts/import_graphify.py`).

## Memory budget

- web and API should remain lightweight when idle
- maximum active heavy model: 1
- normal context budget: 4K on low available RAM, 8K otherwise
- new heavy engine blocked below 1.5 GB available RAM
- model weights excluded from repository

## Environment

See `.env.example`. Production/public contributions must never commit `.env`.
