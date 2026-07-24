# InMyAI QA Report

Date: 2026-07-24 (updated after Phase 2's core-flow fixes; earlier updates from the Explorer + Terminal tabs, the v1/v2 merge, Agents Workspace panel, and config fix are folded in below; original visual pass is from 2026-07-21 and is called out explicitly where it has not been re-verified)

## Automated result (this session)

| Check | Result |
|---|---|
| Strict TypeScript (`tsc --noEmit`) | PASS |
| Frontend tests (`node --test`) | 15/15 PASS |
| FastAPI tests (`pytest services/api/tests`) | 134/134 PASS |
| In-process API smoke check (`scripts/smoke_check.py`) | PASS — see `SMOKE_REPORT.json` |
| Engine simulation x3 (`scripts/simulate_engine.py`) | PASS — see `docs/qa/ENGINE_SIMULATION_3X.json` |
| Next.js production build (`next build`) | PASS — see note below |
| Visual/screenshot regression | NOT RE-RUN — Playwright is not installed in this sandbox; the 2026-07-21 visual pass below has not been re-verified against the Agents/Explorer/Terminal/Phase-2-nav tabs |
| Tauri desktop shell (`cargo tauri dev`) | PASS — confirmed on Windows: compiled clean, opened a real native window. Two bugs found and fixed on first runs (`allowedDevOrigins` in `next.config.mjs`, missing `capabilities/default.json`), see `docs/decisions/tauri-desktop-shell.md` sections 7–8 |

`next build` was run against a copy of `apps/web` outside this sandbox's
FUSE-mounted project folder (an `rsync` into `/tmp`, `node_modules` fetched
fresh there): compiled and prerendered cleanly, including the fix for the
SSR crash `@xterm/xterm` caused (see
`docs/decisions/explorer-and-terminal.md`, section 7). Running it directly
on the mounted folder in this sandbox hits an unrelated `Bus error` — a
sandbox mmap artifact, not a code issue — so this workaround is what
actually verifies the build, not a substitute for it. Your own machine's
normal filesystem doesn't have this constraint; `npm run build` there
should just work.

The 134 backend tests include everything from the original P0 build plus
regression coverage added since: multi-agent task orchestration
(`test_agent_runtime.py`), PPTX indexing (`test_office_indexing.py`),
stale-write detection (`test_core.py`), the dependency-free `apps/local-ui`
static mount (`test_local_ui.py`), the `INMYAI_*` env-prefix binding fix
(`test_config.py`), the mind-map browse endpoint (`test_browse.py`, 8
tests), the interactive terminal's `PtySession` (`test_terminal.py`, 5
tests), the UI-managed allowed-roots settings (`test_allowed_roots.py`,
8 tests), and Phase 2's core-flow fixes: background auto-indexing with a
queryable status machine (`test_index_status.py`, 7 tests), the
folder-scope guardrail (`test_folder_scope.py`, 9 tests), and the Graphify
import HTTP endpoint (2 new tests appended to `test_import_graphify.py`).
`test_git_tools.py` (9 tests, read-only git status/log/diff/branch/
blame) is part of that 134 and passes cleanly on a normal filesystem; see
the note in `docs/decisions/v1-v2-merge-and-agents-panel.md` if it fails
specifically inside a FUSE-mounted sandbox directory — that is an
environment artifact, not a code defect. Running all 134 as one command in
this sandbox occasionally exceeds a 40-second budget purely from cumulative
FUSE I/O (auto-indexing now runs on every project any test file creates,
not just indexing-specific tests) — confirmed as slowness, not a hang, by
running the same 134 tests split into three batches, all green in under a
minute combined; see `docs/decisions/phase2-core-flow.md` section 6.

## What changed since the 2026-07-21 pass

- Merged InMyAI v2's unique, real capabilities into this codebase: multi-agent
  task orchestration (`agent_runtime.py`), stale-write detection + atomic
  writes, PPTX indexing, and the dependency-free `apps/local-ui`.
- Added an "Agents" tab to the Next.js Workspace (`AgentsView` in
  `Workspace.tsx`).
- Fixed the `INMYAI_*` environment-variable prefix so documented overrides
  (`INMYAI_PROVIDER`, `INMYAI_ALLOWED_ROOTS`, etc.) actually bind.
- InMyAI v2 itself has been retired — this repository is now the single
  source of truth for the project.
- Added an "Explorer" tab: a mind-map style folder/file browser
  (`GET /api/browse`) that lets you look around anywhere on disk — names
  only, no content — before deciding what to register as a project.
- Added a "Terminal" tab: a real interactive shell (PowerShell on Windows,
  your default shell on POSIX) over a WebSocket PTY relay
  (`/ws/terminal`) — explicitly not sandboxed.
- The app now has nine primary surfaces instead of five.
- Fixed a real Terminal crash (`Cannot read properties of undefined
  (reading 'dimensions')`) caused by a dev-mode React Strict Mode /
  xterm.js dispose race, and a misleading "Add a local project to begin."
  subtitle shown on the two tabs that don't need one.
- Added a Settings UI (`GET/POST/DELETE /api/settings/allowed-roots`) to
  manage allowed project folders without editing `.env` or restarting -
  including a one-click "Allow this folder & retry" fix inline in the
  registration error itself, plus an inline in-browser folder picker.
- Started a Tauri desktop shell (`apps/web/src-tauri`, `npm run
  desktop:dev`): dev-mode native window + a real OS folder picker, wired
  into Settings and Explorer. Production installer packaging is a
  follow-up (see `docs/decisions/tauri-desktop-shell.md`).
- Phase 2 core-flow fixes: new projects now auto-index in the background
  with a visible progress banner instead of silently requiring a manual
  click; a folder-scope guardrail warns before registering a system/
  profile/drive-root folder; Explorer can overlay a project's code
  relations (the same data Graph shows) directly on its radial browser,
  and Graph gained a real Graphify `graph.json` import button; the 9-tab
  sidebar is now a 5-item Main group plus a collapsible Advanced group
  (Memory/Studio/Git/Agents), persisted per-user in `localStorage`. See
  `docs/decisions/phase2-core-flow.md`.

Full rationale for each decision: `docs/decisions/v1-v2-merge-and-agents-panel.md`,
`docs/decisions/explorer-and-terminal.md`, `docs/decisions/allowed-roots-ui.md`,
`docs/decisions/tauri-desktop-shell.md`, and `docs/decisions/phase2-core-flow.md`.

## Smoke workflow

See `SMOKE_REPORT.json`, regenerated by `scripts/smoke_check.py` against the
bundled `examples/synthetic-project`: health, hardware, project registration,
incremental indexing, FTS search, Safe Mock chat with citations,
model-runtime status, and the full agent task pipeline (`agents` list,
`POST /api/tasks`, `POST /api/tasks/{id}/run`) through to a `completed`
checkpoint. Explorer's `GET /api/browse` and the Terminal's `/ws/terminal`
PTY relay are covered by their own dedicated test files
(`test_browse.py`, `test_terminal.py`) rather than the smoke script, since
one browses the live sandbox filesystem and the other spawns a real shell
process — see `docs/decisions/explorer-and-terminal.md` for why.

## Visual verification (2026-07-21, not re-verified this session)

Reference concept:

- `docs/reference/inmyai-usage-concept.png`

Rendered evidence from the original pass:

- `docs/qa/workspace-desktop.png` — 1536×1024
- `docs/qa/workspace-mobile.png` — 390×844

These screenshots predate the Agents tab and the mobile nav going from six to
seven items, so they no longer reflect the current UI exactly. Re-running a
visual pass needs Playwright + a Chromium binary, neither of which is
installable in this sandbox (no network access). Recommendation: open the
Workspace locally (`npm run dev`) and eyeball the new Agents tab and the
7-column mobile bottom nav before relying on this section again.

Chromium in the *original* build environment blocked navigation to all
localhost, private-IP, and `file://` URLs with `ERR_BLOCKED_BY_ADMINISTRATOR`,
so that pass verified live HTTP behavior through API smoke calls and direct
HTTP response checks, ran Playwright Chromium under Xvfb, and rendered the
production CSS and representative DOM via `page.set_content` for the
screenshot comparison above.

## Five visual comparison points (historical, from the 2026-07-21 pass)

1. **App skeleton:** left project navigation, central workspace, right context rail retained.
2. **Palette:** true white surfaces, quiet gray background, compact dark typography, restrained blue selection state retained.
3. **Chat anatomy:** assistant/user messages, context explanation, source chips, and bottom composer retained.
4. **Safety visibility:** controlled file tools, model/runtime status, RAM profile, and one-engine policy are visible.
5. **Responsive behavior:** desktop sidebars collapse into a mobile bottom navigation (now nine items, one per surface) without horizontal overflow — not re-verified visually this session, but the CSS grid was updated to match.

## Above-the-fold copy diff

No unapproved marketing hero, decorative eyebrow, fake metric, or capability claim was added. The implementation uses product-native workspace copy; the new Agents tab copy follows the same convention (plain description of what the Coordinator/Researcher/Worker/Verifier pipeline does, no unverifiable claims).

## Intentional deviations

- The original concept contained seven sidebar utilities; the shipped implementation consolidated them into five primary surfaces (Search embedded in Files/Graph, Tasks contextual, Settings a modal). Agents is now a sixth *added* surface on top of that baseline (not from the original concept) — a first-class tab, because task checkpoints benefit from a persistent, revisitable view rather than a modal.
- The concept depicts a finished AI image. Core P0 instead labels the generated preview as a simulator. Real AI generation requires a user-configured local ComfyUI or optional Diffusers model.
- Real Ollama response quality and GPU/VRAM benchmarks were not tested because no local model weights/runtime were available in the build environment.
- Dockerfiles were reviewed but not container-built because Docker is unavailable in the build environment.

## Conclusion

Core source, persistence, retrieval, routing, controlled local file workflow, OCR, Safe Mock orchestration, multi-agent task orchestration, the mind-map Explorer, the interactive Terminal, and the Phase 2 core-flow fixes (auto-indexing, folder-scope guardrail, Explorer+Graph relations overlay, Main/Advanced nav split) all pass their automated tests (134 backend + 15 frontend + a live in-process smoke check + a real `next build`). A fresh visual/screenshot pass could not be re-run in this sandbox (no Playwright) and should be run once on a normal machine before treating the UI as fully re-verified end to end — and the Terminal's actual shell behavior (PowerShell on Windows specifically) needs a live check on your machine per `docs/decisions/explorer-and-terminal.md` section 5, since a real shell process can't be meaningfully exercised end-to-end inside this sandbox. Absolute freedom from bugs across every Windows driver, Ollama model, ComfyUI workflow, and private repository cannot be guaranteed; provider-specific acceptance testing remains required.
