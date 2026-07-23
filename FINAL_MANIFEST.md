# Final Manifest

Updated 2026-07-23 after the v1/v2 merge, the Agents Workspace panel, the
`INMYAI_*` config fix, and the Explorer + Terminal tabs. See `QA_REPORT.md`,
`docs/decisions/v1-v2-merge-and-agents-panel.md`, and
`docs/decisions/explorer-and-terminal.md` for detail.

- Project: InMyAI (InMyAI-v2 retired; this repository is the single source of truth)
- Version: 0.1.0
- Frontend: Next.js 16.2.10 + React 19.2.7 + TypeScript — 9 Workspace surfaces (Chat, Files, Memory, Graph, Studio, Git, Agents, Explorer, Terminal)
- Secondary UI: `apps/local-ui`, dependency-free, served by the API at `/app/` — kept permanently as a lightweight fallback
- Backend: FastAPI + SQLite FTS5, multi-agent task orchestration (`agent_runtime.py`: Coordinator/Researcher/Worker/Verifier), mind-map folder browsing (`GET /api/browse`), interactive terminal PTY relay (`/ws/terminal`)
- Frontend tests: 14 passed
- API tests: 107 passed
- In-process smoke check: passed (`scripts/smoke_check.py`, see `SMOKE_REPORT.json`)
- Engine simulation x3: passed (`scripts/simulate_engine.py`, see `docs/qa/ENGINE_SIMULATION_3X.json`)
- Next.js production build: passed this session (built from an `/tmp` copy outside the sandbox's mounted folder — see `QA_REPORT.md`); run `npm run build` on your own machine too, it has no such constraint
- npm production audit / Python dependency check: not re-run this session; last known-good result was 0 vulnerabilities / passed (2026-07-21)
- Visual reference: docs/reference/inmyai-usage-concept.png
- Desktop/mobile renders: docs/qa/workspace-desktop.png, docs/qa/workspace-mobile.png — predate the Agents/Explorer/Terminal tabs and 9-column mobile nav, not re-rendered this session
- Terminal requires `pip install pywinpty` on Windows (Linux/macOS need nothing extra) and `npm install` for `@xterm/xterm` — see `docs/decisions/explorer-and-terminal.md` section 5 for the exact end-to-end check to run on your machine
- Public GitHub documentation: docs/github-repository.md
- License: Apache-2.0
