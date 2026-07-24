# Decision record: Phase 2 core-flow fixes (auto-index, folder guardrail, Explorer+Graph, nav split)

Date: 2026-07-24
Status: done, verified, committed on `main`

Same purpose as the other records in this folder: what the problem was, what
was built, why, what else was considered, and how to check it yourself.

## 1. The problem

After the Tauri desktop shell landed, a real end-to-end walkthrough on your
machine surfaced a different class of problem than "does it compile" -
confusion in normal use. You registered a project ("tes"), then found Chat,
Files, Memory, and Graph all looking empty/broken, and asked nine separate
questions about tabs whose purpose wasn't obvious (Graph, Studio, Git,
Agents). Root-caused down to one thing: indexing was a silent manual step
(click a small refresh icon) with no visible consequence if you forgot it -
every "empty" tab you saw was actually just "nothing indexed yet," not a bug.
A second, separate problem: the native folder picker made it easy to
register a folder far wider than intended (the whole `demo` folder, which
contains many unrelated client projects, as one project called "tes").

This record covers the four-task plan that followed
(`docs/superpowers/plans/2026-07-24-phase2-core-flow.md`,
spec at `docs/superpowers/specs/2026-07-24-phase2-core-flow-design.md`):
auto-indexing with visible progress, a folder-scope guardrail, merging
Explorer's radial browser with Graph's code-relation data, and splitting the
9-tab nav into a 5-item Main group plus a collapsible Advanced group.

## 2. Task 1 - auto-index + progress, so "empty" only ever means "genuinely nothing there"

**Backend:** `POST /api/projects` now schedules indexing as a FastAPI
`BackgroundTasks` job immediately after creating the row (`status='pending'`
instead of the old `'ready'`), so a newly-registered project starts indexing
itself without a separate click. A new `index_progress` table
(`database.py`, `CREATE TABLE IF NOT EXISTS`, same idempotent pattern as
every other table here) tracks `phase`/`total_files`/`processed_files`/
`error` per project, written to during `index_project()`'s file loop
(`indexer.py`). `GET /api/projects/{id}/index-status` exposes that for
polling; `POST /api/projects/{id}/index` (manual re-index) now returns `409`
if a background index is already running, instead of racing it. Startup
runs `services.reset_interrupted_indexing()` (called from `lifespan`) so a
project stuck at `status='indexing'` from a crashed previous run gets moved
back to `pending` with a recorded "interrupted" error, rather than looking
permanently stuck.

**Frontend:** `Workspace.tsx` polls `index-status` every 1.5s while a project
is `pending`/`indexing` and renders a progress banner ("Indexing project...
42/113 files") right under the topbar; a failed index shows an inline Retry
button instead of a dead end. The Context rail's "Not indexed yet" line is
now status-aware (`Queued for indexing...` / `Indexing...` / `Indexing
failed - retry from the toolbar` / the indexed timestamp).

**Tests:** `services/api/tests/test_index_status.py` (7 tests) - auto-index
reaching `ready`, the status endpoint's shape, 404 on an unknown project, the
409 double-index guard, a failed index recording its error, and orphan
recovery on startup.

## 3. Task 2 - folder-scope guardrail

**Backend:** `services.classify_folder_scope(path)` flags genuine accident
targets - the user's profile root, `Documents`/`Desktop`/`Downloads`, a drive
root (`C:\`) or filesystem root (`/`) - as `is_dangerous`. A folder that
merely contains many sibling projects (your actual cross-project workflow)
is deliberately **not** flagged dangerous; it only gets a non-blocking
`large_folder: true` at >20 direct subdirectories, surfaced as a console
hint, not a dialog. `GET /api/projects/scope?path=...` exposes this
classification without mutating anything.

**Frontend:** both registration paths (Settings' "Add a local project" form
and Explorer's "Open as project") call this endpoint before `POST
/api/projects` and show a native `window.confirm` when `is_dangerous` is
true, naming what matched ("looks like your user profile root"). Continuing
is still possible - this is a guardrail against slips, not a hard block.

**Tests:** `services/api/tests/test_folder_scope.py` (9 tests, one
conditionally skipped if `~/Documents` doesn't exist on the machine running
the suite) - covers all the dangerous cases, a normal project directory
staying unflagged, the subdirectory count, the >20 non-blocking case, and
both HTTP paths through `/api/projects/scope`.

## 4. Task 3 - Explorer gained code relations; Graph gained a real Graphify import button

Rather than pick one of "keep them separate" or "merge them," this
implements the version of "merge" that doesn't throw away either tab's
purpose: Explorer stays a general disk browser (works on any folder, indexed
or not), but when the folder you're currently looking at *is* the active,
indexed project, a **Relations** toggle appears in its toolbar. Turning it on
overlays the same import/defines/calls edges Graph already computes (color-
coded by relation type, capped at 60 edges with a pointer to the Graph tab
for anything past that) directly on the radial mind-map, matched by
filename against the currently-positioned nodes. The toggle's state persists
in `localStorage` across navigation. Browsing the active project before it's
indexed shows a one-line hint ("Index this project to see code relations
here") instead of silently showing nothing.

Separately, Graph's own import path went from a footer caption ("Graphify
graph.json can be integrated as an additional source") to an actual button:
`POST /api/projects/{id}/graph/import` accepts a Graphify-shaped
`{nodes, edges}` payload and inserts each edge into `relations` tagged
`confidence='INFERRED'` (supplementing, not replacing, the deterministic
AST-extracted edges). The Graph tab has a file input next to the trace
search box that posts to this endpoint and immediately refreshes the graph.

**Tests:** `services/api/tests/test_import_graphify.py` gained two HTTP-level
tests (the endpoint accepts a payload and 404s on an unknown project) on top
of its existing coverage of the underlying `services.import_graphify`.

## 5. Task 4 - nav split into Main (5) + collapsible Advanced (4)

Chat, Files, Explorer, Graph, and Terminal are the tabs someone uses in a
normal session; Memory, Studio, Git, and Agents are real but occasional.
`Workspace.tsx`'s single `nav` array became `navMain` + `navAdvanced`,
rendered as two groups in the sidebar with an "Advanced" header that expands/
collapses (persisted in `localStorage`, and auto-expanded whenever the
active view happens to be one of the four Advanced tabs, so a deep link or a
restored `view` state is never hidden behind a collapsed section). Nothing
was removed or hidden permanently - `MobileNav` still shows all nine flat
(no room to collapse on a phone-width layout), and the topbar's title lookup
was updated to search both groups.

**Tests:** `apps/web/tests/routing.test.mjs` gained a data-level assertion
that the two groups don't overlap and their union is exactly the original
nine surfaces - a guard against silently dropping a tab in a future edit.

## 6. What was found and fixed during verification, beyond the plan's own steps

The plan's four tasks were already implemented and committed (by an agentic
session run against this same plan) by the time this record's author
verified them. Verification found and fixed two things the plan itself
didn't cover:

- **A leftover duplicate declaration:** Task 4's commit introduced a
  module-scope `ADVANCED_NAV_KEY` constant but left an old local `const
  ADVANCED_NAV_KEY` inside the `Workspace` component too (harmless -
  JavaScript scoping means the inner one just shadowed the outer one - but
  dead, confusing code). Removed the duplicate local declaration; the
  module-scope one is now the only definition. See commit `565f590`.
- **Full backend suite runtime grew noticeably (134 tests, up from 115):**
  auto-indexing on every `POST /api/projects` call (Task 1) means every
  *other* test file that creates a project for unrelated reasons
  (`test_ast.py`, `test_core.py`, `test_git_tools.py`, etc.) now also
  triggers a real synchronous index pass under `TestClient` (Starlette runs
  `BackgroundTasks` synchronously after the response returns). Measured in
  this sandbox: running the suite as one command occasionally exceeds a 40s
  budget purely from cumulative I/O on this environment's FUSE-mounted
  project folder - a "how" of *this sandbox specifically*, not a hang or a
  failure (splitting the same 134 tests into three sequential batches
  completes all of them, all green, in under 60s combined; `user`+`sys` CPU
  time across all batches is under 10s, meaning the wall-clock time is I/O
  wait, not computation or an infinite loop). This is the same category of
  environment artifact already documented for `next build` on this mount
  (see `explorer-and-terminal.md` section 7) - expected to be a non-issue on
  your actual Windows machine's local disk. No code change was made for
  this; flagged here so it isn't mistaken for a regression later.

## 7. What was deliberately not built

Task 5 from the original prompt (production packaging: Next.js static
export, a bundled Python sidecar, code signing, cross-platform CI builds)
was explicitly out of scope for this pass, same rationale as
`tauri-desktop-shell.md` section 3 - it's a separate, larger body of work
that doesn't block today's actual pain point.

## 8. How to verify

```bash
python -m pytest services/api/tests -q
cd apps/web && npx tsc --noEmit && npm run test && npm run build
```

All green: 134 backend tests, 15 frontend tests, clean typecheck, clean
production build (built from a clean `/tmp` copy per the established
sandbox workaround - `npm install` then `npm run build` - since building
directly on this sandbox's mounted folder hits the unrelated `Bus error`
mmap artifact documented elsewhere in this repo).
