# Phase 2 — Core Flow Fixes (Indexing, Guardrail, Explorer+Graph, Nav)

**Date:** 2026-07-24
**Status:** Approved (brainstormed 2026-07-24)
**Scope:** 4 sequential tasks. Each shipped + tested + committed before the next. Task 5 (packaging) out of scope.

---

## Context & Problem

InMyAI has 9 tabs and works, but real usage surfaced two root causes of user confusion (not broken features):

1. **Indexing is invisible and manual.** `POST /api/projects` does NOT index. Only the toolbar "Index project" button does, synchronously/blocking. The only "not indexed" surface is one `<small>` line in `ContextRail`. So Chat/Files/Memory/Graph look "empty/broken" when the project simply has no data yet.
2. **Native folder picker has no guardrail.** A user can accidentally register `Documents`/`C:\` as one project and auto-index thousands of irrelevant files.

Plus two IA/UX tasks: merge Explorer (radial folder mind-map) and Graph (AST relations) into one coherent view, and simplify the 9-tab surface.

## Decisions (from brainstorming)

| Task | Decision | Rationale |
|---|---|---|
| 1 Indexing | **Auto-trigger background + progress UI** | Meets acceptance: project usable after create with no extra action. FastAPI `BackgroundTasks` (native, no Celery). |
| 2 Guardrail | **Dangerous-path modal + non-blocking info >20 subfolders** | User's real workflow registers wide parent folders (e.g. `.../ideagentics`) to cross-reference projects — a naive >5 threshold would false-positive. Guard only against accidents. |
| 3 Explorer+Graph | **Opsi A: overlay code relations on the radial Explorer** | One coherent view, matches Graphify inspiration. |
| 4 Nav | **2 groups: Main + Advanced collapsible (localStorage)** | Matches explicit prompt instruction. |

---

## Task 1 — Auto-indexing + progress UI

### Backend

**Status machine** — reuse existing `projects.status` column (no schema migration; additive values only):
- `'pending'` — created, never indexed (new insert default, replaces `'ready'`)
- `'indexing'` — background task running
- `'ready'` — done (existing value; `indexed_at` set)
- `'failed'` — error; `indexed_at` stays NULL, `audit_log` records reason

**Trigger:** `POST /api/projects` → after insert with `status='pending'`, schedule `index_project` via `fastapi.BackgroundTasks`. Request returns immediately with the project object (HTTP 200, same shape as today). Non-blocking.

**Progress table** (idempotent `CREATE TABLE IF NOT EXISTS` in `database.py`, follows existing migration convention):
```sql
CREATE TABLE IF NOT EXISTS index_progress (
    project_id INTEGER PRIMARY KEY,
    phase TEXT NOT NULL,            -- 'scanning' | 'indexing' | 'done' | 'failed'
    total_files INTEGER NOT NULL DEFAULT 0,
    processed_files INTEGER NOT NULL DEFAULT 0,
    started_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    error TEXT
);
```

**New endpoint:** `GET /api/projects/{id}/index-status` → `{status, phase, total_files, processed_files, error, indexed_at}`. Cheap read; frontend polls ~1.5s while `status in ('pending','indexing')`.

**Indexer changes** (`indexer.py`):
- Signature: `index_project(project_id, root, progress_cb=None)`.
- Before processing: set `projects.status='indexing'`, `index_progress` row `phase='scanning'`, count total via `iter_indexable_files` (cheap walk, no reads).
- During: `phase='indexing'`, increment `processed_files` per file (or per batch of N for write perf). `progress_cb` wrapped so a logging failure can't crash indexing.
- On success: `status='ready'`, `indexed_at=now`, `phase='done'` (existing audit_log `project.indexed` retained).
- On exception: `status='failed'`, `phase='failed'`, `error=str(exc)`, audit_log `project.index_failed`.

**Orphan recovery** (app startup, in `main.py` lifespan or a startup hook): any row with `status='indexing'` → reset to `'pending'` + `index_progress.phase='failed', error='interrupted'`. Background tasks don't survive restart; no zombie state.

**Double-index guard:** `POST /api/projects/{id}/index` returns **409** if `status=='indexing'`.

### Frontend

- Toolbar "Index project" button stays (manual re-index).
- After successful create (modal `addProject` AND `registerProjectFromExplorer`): start polling `index-status`; show global progress banner.
- **Global progress banner** above content area (single persistent place, not per-tab): `Indexing project… 142/300 files` + progress bar. Visible whenever active project `status in ('pending','indexing')`.
- **Failed banner:** `Indexing failed: {error}` + "Retry" button (calls `/index` again).
- Chat/Files/Memory/Graph when `status != 'ready'`: clear empty state (`Waiting for index to finish…`), not "looks broken/empty".
- Polling stopped on project switch, tab unload, or `status in ('ready','failed')`.

### Edge cases / error handling
- Folder unreadable mid-index → `status='failed'` with reason.
- App closed mid-index → orphan recovery on next start.
- Concurrent `/index` calls → 409 on the second.
- Path outside allowed roots → indexer raises → `failed` with clear message.

### Tests
- Backend: auto-trigger fires (assert `status` reaches `indexing`); transitions `pending→indexing→ready` and `→failed`; orphan recovery resets `indexing` rows; 409 on double; `index-status` returns monotonic counts.
- Frontend: banner shows for `pending`/`indexing`; polling starts/stops; retry CTA re-triggers.

---

## Task 2 — Guardrail for too-wide folders

### Backend

**Helper** in `services.py` (or a new `folder_scope.py`): `classify_folder_scope(path) -> dict`:
```python
{
  'is_dangerous': bool,
  'dangerous_match': str | None,   # which pattern matched, e.g. 'Documents'
  'direct_subdirs': int,           # count of immediate subdirectories
}
```

**Dangerous detection** — resolve path to absolute, compare (case-insensitive on Windows) against well-known accident targets:
- User profile root (`C:\Users\<name>`)
- `Documents`, `Desktop`, `Downloads`, `Home` (`~`)
- Drive roots: `C:\`, `D:\`, `\`
- OS dirs: `Windows`, `Program Files`, `Program Files (x86)`

Detection = exact match OR is-a-parent-of (e.g. `C:\Users\Amand` matches profile root). Implemented with `Path.resolve()` and `parts` comparison — robust against trailing separators and `..`.

**Endpoint:** `GET /api/projects/scope?path=...` → returns the classification dict. Reuses allowed-roots resolution so it works inside Tauri and browser equally. Does NOT mutate anything.

`POST /api/projects` unchanged structurally — it still accepts `{name, path}`. The frontend consults `/scope` BEFORE posting and gates the post behind user confirmation when needed.

### Frontend

In both registration flows (`SettingsModal.addProject`, `registerProjectFromExplorer`):
1. After path is selected (native picker or inline browser), call `GET /api/projects/scope?path=...`.
2. **If `is_dangerous`** → modal dialog (blocking): `Folder "{path}" looks like a system folder ({dangerous_match}). Registering it will index everything inside. Continue?` with **Cancel** (default) / **Continue anyway**.
3. **Else if `direct_subdirs > 20`** → inline non-blocking notice under the path field (not a modal): `Note: this folder has {N} subfolders. Large folders take longer to index.` No gate; user proceeds normally.
4. **Else** → no notice, proceed silently (workflow cross-project like `.../ideagentics` stays frictionless).

### Edge cases
- Path doesn't exist → existing `POST` validation handles (400).
- Picker returns path inside allowed roots but dangerous (e.g. allowed `C:\Users\Amand`, picked `C:\Users\Amand`) → still flagged.
- Classification fails (permission) → treat as non-dangerous, let `POST` validation surface the real error.

### Tests
- Backend: `classify_folder_scope` flags each dangerous pattern; passes on normal project dir; counts subdirs correctly; case-insensitive on Windows.
- Frontend: dangerous path → modal blocks POST until confirmed; >20 subdirs → inline notice, no block; normal path → silent.

---

## Task 3 — Merge code relations into radial Explorer (Opsi A)

### Goal
When the folder being browsed in Explorer IS the active project AND that project is `status='ready'`, overlay code relations (imports/defines/calls from the AST `relations` table) as edges on the same radial mind-map. Plus expose Graphify `graph.json` import in the Graph tab UI.

### Backend

No new endpoints needed. Explorer already uses `GET /api/browse?path=...` (folder entries). Graph already uses `GET /api/projects/{id}/graph` (relations). The frontend joins them client-side.

**Graphify import** — `services.import_graphify(project_id, graph_dict)` already exists (`confidence='INFERRED'`). Add endpoint `POST /api/projects/{id}/graph/import` accepting a `graph.json` body (multipart file or JSON). Follows existing route structure in `main.py`. Returns counts imported. Audits `project.graph_imported`.

### Frontend (Explorer)

In `ExplorerView`:
1. Detect: is `currentBrowsePath` the same as `activeProject.path` (resolve & compare)? Is `activeProject.status === 'ready'`?
2. If both true → fetch `GET /api/projects/{id}/graph` once (cache per session), build an edge list: for each relation `(source_node, target_node)`, find the radial nodes whose path matches `source_node`/`target_node` (relative-path match against entry paths).
3. **Toggle** "Show code relations" (default OFF — radial can be crowded; user opts in). Persisted in localStorage `inmyai:explorer:showRelations`.
4. **Edge rendering** — draw edges as subtle quadratic curves with low opacity (e.g. `stroke-opacity=0.25`, thin stroke) UNDER the node layer so nodes stay clickable and readable. Edge color encodes relation type (import=blue, define=green, call=amber). Hover/click an edge → mini inspector showing `(source → target, relation, evidence)`.
5. Node-edge collision avoidance: edges routed as curves bowing outward from center; max edge count capped (e.g. 60) to prevent hairball — beyond that, show "N relations hidden, filter in Graph tab" hint.
6. If `status != 'ready'` → show inline hint in Explorer: "Index this project to see code relations here." (cross-links to Task 1 banner / Graph tab).

### Frontend (Graph tab)

- Add "Import Graphify graph.json" button (file input). POSTs to new endpoint. On success, reload graph + toast.
- Make the existing footer caption about Graphify integration a real affordance, not just text.

### Edge cases
- Project not indexed yet → Explorer shows hint, no edges (no crash on empty relations).
- Path match: relations use relative paths; browse entries have full paths → normalize via `Path.relative_to(project_path)` for matching. Unmatched edges skipped silently.
- Huge relation count → cap + hint (above).
- Graphify import with malformed JSON → 400 with message.

### Tests
- Backend: new import endpoint accepts valid `graph.json`, rejects malformed, counts correct, idempotent re-import.
- Frontend: relations render only when browse path == project path AND ready; toggle persists; cap enforced; edge click shows inspector.

---

## Task 4 — Simplify nav: Main + Advanced collapsible

### Change

Split the single `nav` array in `Workspace.tsx` into two:
```tsx
const navMain: NavItem[] = [
  { id: 'chat', ... }, { id: 'files', ... }, { id: 'explorer', ... },
  { id: 'graph', ... }, { id: 'terminal', ... },
];
const navAdvanced: NavItem[] = [
  { id: 'memory', ... }, { id: 'studio', ... }, { id: 'git', ... }, { id: 'agents', ... },
];
```

Render: main group always visible; advanced group under a collapsible header "Advanced ▾/▸". Collapse state in `localStorage` key `inmyai:nav:advancedExpanded`, default `false`.

**Auto-expand on selection:** if the active `view` is in `navAdvanced` and the group is collapsed, expand it automatically so the active tab is always visible/highlighted (and stays highlighted). User can collapse again manually.

No features removed. `View` type unchanged. No backend changes.

### Tests
- Frontend: default shows 5 main tabs, Advanced collapsed; expanding reveals 4; state persists across reload; selecting an advanced tab auto-expands; active tab highlighted in either group.

---

## Cross-cutting

### Order & gates
Sequential: Task 1 → 2 → 3 → 4. Each task: implement → run full verification suite → commit (separate commit, clear message) → start next.

### Verification suite (must stay green)
- `pytest services/api/tests` — 115 passing (will grow with new tests).
- `npm run test` in `apps/web` — 14 passing (will grow).
- `npx tsc --noEmit` in `apps/web` — clean.
- `npm run build` in `apps/web` — clean.

### Docs
- New `docs/decisions/phase2-core-flow.md` following existing format (problem / reasoning / what changed / how to verify).
- Update `QA_REPORT.md` (test table + change summary) after all tasks.

### Follow-existing-patterns
- SQLite migrations: additive `CREATE TABLE IF NOT EXISTS` / `ALTER TABLE ADD COLUMN` swallowed on dup (database.py convention).
- New endpoints follow `main.py` route structure (try/except → HTTPException, services-layer logic).
- Frontend follows existing component patterns in `Workspace.tsx`; `localStorage` keys namespaced `inmyai:*`.

## Out of scope (Task 5)
Production packaging (Tauri static export + Python sidecar + code signing + cross-OS CI). Not started unless explicitly requested.
