# Final Manifest

Updated 2026-07-23 after the v1/v2 merge, the Agents Workspace panel, and the
`INMYAI_*` config fix. See `QA_REPORT.md` and
`docs/decisions/v1-v2-merge-and-agents-panel.md` for detail.

- Project: InMyAI (InMyAI-v2 retired; this repository is the single source of truth)
- Version: 0.1.0
- Frontend: Next.js 16.2.10 + React 19.2.7 + TypeScript — 7 Workspace surfaces (Chat, Files, Memory, Graph, Studio, Git, Agents)
- Secondary UI: `apps/local-ui`, dependency-free, served by the API at `/app/` — kept permanently as a lightweight fallback
- Backend: FastAPI + SQLite FTS5, multi-agent task orchestration (`agent_runtime.py`: Coordinator/Researcher/Worker/Verifier)
- Frontend tests: 14 passed
- API tests: 94 passed
- In-process smoke check: passed (`scripts/smoke_check.py`, see `SMOKE_REPORT.json`)
- Engine simulation x3: passed (`scripts/simulate_engine.py`, see `docs/qa/ENGINE_SIMULATION_3X.json`)
- Next.js production build: not verified this session (sandbox has no network for the SWC binary) — run `npm run build` on a normal machine
- npm production audit / Python dependency check: not re-run this session; last known-good result was 0 vulnerabilities / passed (2026-07-21)
- Visual reference: docs/reference/inmyai-usage-concept.png
- Desktop/mobile renders: docs/qa/workspace-desktop.png, docs/qa/workspace-mobile.png — predate the Agents tab and 7-column mobile nav, not re-rendered this session
- Public GitHub documentation: docs/github-repository.md
- License: Apache-2.0
