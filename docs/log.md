# Project Log

| Timestamp | Status | Update |
|---|---|---|
| 2026-07-21 | SUCCESS | Created InMyAI monorepo with Next.js UI, FastAPI API, SQLite/FTS5, model routing, memory, decisions, graph, controlled file writes, OCR, image simulator, tests, and documentation. |
| 2026-07-21 | SUCCESS | Verified strict TypeScript, frontend tests, FastAPI tests, Tesseract OCR test, and Next.js production build. |
| 2026-07-21 | PARTIAL | Real Ollama quality and real diffusion-model image generation require separately installed local runtimes/model weights and target-hardware acceptance testing. |
| 2026-08-11 | SUCCESS | Pinned the loopback web development server to canonical port 3000 so a collision fails clearly instead of silently moving Hub discovery out of sync; added a runtime-binding regression assertion and verified the Windows collision/recovery flow. |
| 2026-08-11 | SUCCESS | Added a strict `inmy.lifecycle.json` contract for the API launcher. It pins the audited runtime source, fixed Node launcher/loopback port, product-local dependencies, sanitized non-secret environment and `contract-only` state; no lifecycle control endpoint was enabled. |
| 2026-08-11 | SUCCESS | Added manager-only graceful API shutdown: the internal loopback endpoint is absent unless Hub injects an ephemeral per-process bearer token, invalid tokens have no effect, and the managed Uvicorn runner exits through `Server.should_exit`. Manual development keeps reload mode. API regression suite passed 143 with 5 environment-dependent skips. |
| 2026-08-11 | SUCCESS | Hardened managed shutdown-token handling: the API consumes the credential from its process environment before serving requests, retains it only in private application state, and regression coverage proves descendant processes cannot inherit it. Full QA passed with 27 web tests, 144 API tests, 5 environment-dependent skips, strict TypeScript, and the production web build. |
