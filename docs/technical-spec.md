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

## Supported indexing formats

- code/text: MD, TXT, JSON, YAML, TOML, INI, Python, JS/TS, CSS, HTML, SQL, shell, PowerShell, Go, Rust, Java, C/C++, C#, PHP, Ruby, Swift, Kotlin
- PDFs with extractable text

Office files are planned as an optional plugin rather than forcing large dependencies into P0.

## Search

SQLite FTS5 with BM25 ordering. The query is tokenized and safely quoted before use in `MATCH`.

## Graph

P0 extracts:

- file imports
- functions/classes/interfaces/types defined by source files

Every built-in edge is tagged `EXTRACTED`. Graphify integration is documented as an additional graph source.

## Memory budget

- web and API should remain lightweight when idle
- maximum active heavy model: 1
- normal context budget: 4K on low available RAM, 8K otherwise
- new heavy engine blocked below 1.5 GB available RAM
- model weights excluded from repository

## Environment

See `.env.example`. Production/public contributions must never commit `.env`.
