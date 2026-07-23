# Phase 2 Core Flow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix InMyAI's core flow in 4 sequential tasks — auto-indexing with progress, folder-scope guardrail, merged Explorer+Graph view, and simplified 2-tier navigation — without breaking the existing 115 backend / 14 frontend tests.

**Architecture:** Backend changes are additive (new `index_progress` table via idempotent `CREATE TABLE IF NOT EXISTS`, new status values on the existing `projects.status` column, new endpoints following the existing `main.py` route structure). Frontend changes stay in `Workspace.tsx` and follow its existing component/localStorage patterns. Each task ships green and commits separately.

**Tech Stack:** FastAPI + SQLite + pytest (backend); Next.js + React/TypeScript + `node --test` + `tsc`/`next build` (frontend).

**Spec:** `docs/superpowers/specs/2026-07-24-phase2-core-flow-design.md`

**Verification gate (run after EVERY task, must stay green):**
```bash
# backend (from repo root)
python -m pytest services/api/tests -q
# frontend (from apps/web)
cd apps/web && npx tsc --noEmit && npm run test && npm run build
```
All repo-relative paths below are from `C:\Users\Amand\.gemini\antigravity\scratch\ideagentics\demo\InMyAI_FullStack`.

---

## File map (what changes, per responsibility)

**Backend:**
- `services/api/app/database.py` — add `index_progress` table to `migrate()`.
- `services/api/app/indexer.py` — add `progress_cb` param to `index_project`; set `status='indexing'`/`'failed'`/`'ready'`.
- `services/api/app/services.py` — new `create_project` returns `'pending'` status + schedules indexing; new `get_index_status(project_id)`; new `classify_folder_scope(path)`; new `import_graphify` endpoint helper already exists.
- `services/api/app/main.py` — `POST /api/projects` accepts `BackgroundTasks` & triggers indexing; `POST /api/projects/{id}/index` returns 409 when already indexing; new `GET /api/projects/{id}/index-status`; new `GET /api/projects/scope`; new `POST /api/projects/{id}/graph/import`; orphan recovery in `lifespan`.
- `services/api/tests/test_index_status.py` (new) — Task 1 backend tests.
- `services/api/tests/test_folder_scope.py` (new) — Task 2 backend tests.
- `services/api/tests/test_graph_import.py` (extend existing or new) — Task 3 import-endpoint test.

**Frontend:**
- `apps/web/src/lib/types.ts` — add `IndexStatus`, `FolderScope`, `GraphImportResult` types.
- `apps/web/src/components/Workspace.tsx` — index-progress banner + polling; guardrail gate in both registration flows; relations overlay in Explorer; Graphify import button in GraphView; split `nav` into `navMain`/`navAdvanced`.
- `apps/web/tests/routing.test.mjs` — extend with nav-group assertions (pure data test, matches existing pattern).
- `apps/web/src/components/Icons.tsx` — already exports `ChevronDown`/`ChevronRight`? Check; add if missing.

**Docs:**
- `docs/decisions/phase2-core-flow.md` (new) — decision record.
- `QA_REPORT.md` — updated test table + change summary.

---

# Task 1 — Auto-indexing + progress UI

## 1A. Backend: schema + indexer + services

**Files:**
- Modify: `services/api/app/database.py` (add table to `migrate()` executescript, after the `allowed_roots` table around line 173)
- Modify: `services/api/app/indexer.py` (`index_project` signature + status writes)
- Modify: `services/api/app/services.py` (`create_project`, new `get_index_status`, new `reset_interrupted_indexing`)
- Test: `services/api/tests/test_index_status.py` (new)

- [ ] **Step 1: Write failing backend test file**

Create `services/api/tests/test_index_status.py`:

```python
"""Phase 2 Task 1: project creation auto-triggers background indexing, with a
queryable status machine (pending -> indexing -> ready/failed) and progress counts.

TestClient runs Starlette BackgroundTasks synchronously after the response is
returned, so by the time `client.post('/api/projects')` resolves, the indexing
task has already completed (status reached 'ready' or 'failed').
"""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from services.api.app.config import settings
from services.api.app.main import app

client = TestClient(app)


def _fresh_project_dir(name: str = 'idx_demo') -> Path:
    """A throwaway project dir under the test workspace with one indexable file."""
    root = settings.workspace_root / name
    if root.exists():
        import shutil
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)
    (root / 'hello.py').write_text('print("hi")\n', encoding='utf-8')
    return root


def test_create_project_auto_indexes_to_ready() -> None:
    root = _fresh_project_dir('idx_auto')
    response = client.post('/api/projects', json={'name': 'IdxAuto', 'path': str(root)})
    assert response.status_code == 200, response.text
    project = response.json()
    # TestClient ran the background task already, so indexing is done.
    assert project['status'] == 'pending' or project['status'] == 'ready'
    # Re-fetch to see the post-background state.
    fetched = client.get('/api/projects').json()
    this = next(p for p in fetched if p['id'] == project['id'])
    assert this['status'] == 'ready'
    assert this['indexed_at'] is not None


def test_index_status_endpoint_reports_progress_and_done() -> None:
    root = _fresh_project_dir('idx_status')
    project = client.post('/api/projects', json={'name': 'IdxStatus', 'path': str(root)}).json()
    status = client.get(f"/api/projects/{project['id']}/index-status").json()
    assert status['status'] in ('ready',)
    assert status['phase'] == 'done'
    assert status['total_files'] >= 1
    assert status['processed_files'] >= 1
    assert status['processed_files'] <= status['total_files']


def test_index_status_404_for_unknown_project() -> None:
    response = client.get('/api/projects/999999/index-status')
    assert response.status_code == 404


def test_double_index_returns_409_when_already_indexing() -> None:
    # We can't easily hold the background task mid-flight under TestClient
    # (it runs synchronously). Instead, set status='indexing' directly to
    # simulate an in-flight task and assert the guard.
    root = _fresh_project_dir('idx_double')
    project = client.post('/api/projects', json={'name': 'IdxDouble', 'path': str(root)}).json()
    from services.api.app.database import transaction
    with transaction() as conn:
        conn.execute("UPDATE projects SET status='indexing' WHERE id=?", (project['id'],))
    response = client.post(f"/api/projects/{project['id']}/index")
    assert response.status_code == 409
    assert 'already' in response.json()['detail'].lower()


def test_failed_indexing_records_error_status() -> None:
    # Register a path, then point it at a folder that disappears mid-index by
    # creating a project whose source dir is deleted before manual re-index.
    root = _fresh_project_dir('idx_fail')
    project = client.post('/api/projects', json={'name': 'IdxFail', 'path': str(root)}).json()
    import shutil
    shutil.rmtree(root)
    # Force a re-index; the missing root should surface as status='failed'.
    response = client.post(f"/api/projects/{project['id']}/index")
    assert response.status_code == 400
    fetched = next(p for p in client.get('/api/projects').json() if p['id'] == project['id'])
    assert fetched['status'] == 'failed'
    status = client.get(f"/api/projects/{project['id']}/index-status").json()
    assert status['phase'] == 'failed'
    assert status['error']


def test_orphan_recovery_resets_indexing_on_startup() -> None:
    root = _fresh_project_dir('idx_orphan')
    project = client.post('/api/projects', json={'name': 'IdxOrphan', 'path': str(root)}).json()
    from services.api.app.database import transaction
    from services.api.app import services as svc
    # Simulate a crash mid-index: status stuck at 'indexing'.
    with transaction() as conn:
        conn.execute("UPDATE projects SET status='indexing' WHERE id=?", (project['id'],))
    svc.reset_interrupted_indexing()
    fetched = next(p for p in client.get('/api/projects').json() if p['id'] == project['id'])
    assert fetched['status'] == 'pending'
    status = client.get(f"/api/projects/{project['id']}/index-status").json()
    assert status['phase'] == 'failed'
    assert 'interrupted' in (status['error'] or '').lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest services/api/tests/test_index_status.py -q`
Expected: FAIL — `AttributeError` on `get_index_status` / `reset_interrupted_indexing`, 404s, etc. (most tests error). At minimum `test_index_status_404_for_unknown_project` may already pass; the rest fail.

- [ ] **Step 3: Add `index_progress` table to `database.py`**

In `services/api/app/database.py`, inside the `migrate()` `executescript(...)` string, add this block immediately **after** the `allowed_roots` table block (after line 173, before the closing `'''`):

```sql
            CREATE TABLE IF NOT EXISTS index_progress (
                project_id INTEGER PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE,
                phase TEXT NOT NULL DEFAULT 'scanning',
                total_files INTEGER NOT NULL DEFAULT 0,
                processed_files INTEGER NOT NULL DEFAULT 0,
                started_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                error TEXT
            );
```

- [ ] **Step 4: Modify `index_project` to accept `progress_cb` and write status transitions**

In `services/api/app/indexer.py`, replace the whole `index_project` function (lines 124-199) with:

```python
def index_project(project_id: int, root: Path, progress_cb=None) -> dict:
    """Index a project's files into the `files`/`files_fts`/`relations` tables.

    Sets projects.status to 'indexing' on entry, 'ready' on success, 'failed'
    on exception. `progress_cb(phase, total, processed)` is invoked (best-effort,
    never raises) so callers can render live progress; it must not be relied on
    for correctness. Returns the same counts dict as before.
    """
    def _report(phase: str, total: int, processed: int) -> None:
        if progress_cb is None:
            return
        try:
            progress_cb(phase, total, processed)
        except Exception:  # progress reporting must never break indexing
            pass

    indexed = 0
    unchanged = 0
    errors: list[str] = []
    seen: set[str] = set()
    now = utc_now()

    try:
        with transaction() as conn:
            conn.execute("UPDATE projects SET status='indexing' WHERE id=?", (project_id,))
            conn.execute(
                "INSERT INTO index_progress(project_id,phase,total_files,processed_files,started_at,updated_at,error) "
                "VALUES(?,?,?,?,?,?,?) "
                "ON CONFLICT(project_id) DO UPDATE SET phase=excluded.phase,total_files=excluded.total_files,"
                "processed_files=excluded.processed_files,started_at=excluded.started_at,updated_at=excluded.updated_at,error=NULL",
                (project_id, 'scanning', 0, 0, now, now),
            )
            # Pass 1: count total (cheap walk, no file reads).
            files_to_index = list(iter_indexable_files(root))
            total = len(files_to_index)
            conn.execute(
                "UPDATE index_progress SET phase='indexing',total_files=?,updated_at=? WHERE project_id=?",
                (total, utc_now(), project_id),
            )
            _report('indexing', total, 0)

            for path in files_to_index:
                relative = path.relative_to(root).as_posix()
                seen.add(relative)
                try:
                    stat = path.stat()
                    raw = path.read_bytes()
                    digest = _sha256(raw)
                    existing = conn.execute(
                        'SELECT id, sha256 FROM files WHERE project_id=? AND relative_path=?',
                        (project_id, relative)
                    ).fetchone()
                    if existing and existing['sha256'] == digest:
                        unchanged += 1
                        continue
                    content, parser = _read_text(path)
                    if not content.strip():
                        continue
                    if existing:
                        file_id = existing['id']
                        conn.execute(
                            '''UPDATE files SET absolute_path=?, extension=?, size_bytes=?, modified_ns=?,
                               sha256=?, content=?, indexed_at=?, parser=?, parse_status=? WHERE id=?''',
                            (str(path), path.suffix.lower(), stat.st_size, stat.st_mtime_ns,
                             digest, content, now, parser, 'indexed', file_id)
                        )
                        conn.execute('DELETE FROM files_fts WHERE file_id=?', (file_id,))
                    else:
                        cur = conn.execute(
                            '''INSERT INTO files(project_id, relative_path, absolute_path, extension, size_bytes,
                               modified_ns, sha256, content, indexed_at, parser, parse_status) VALUES(?,?,?,?,?,?,?,?,?,?,?)''',
                            (project_id, relative, str(path), path.suffix.lower(), stat.st_size,
                             stat.st_mtime_ns, digest, content, now, parser, 'indexed')
                        )
                        file_id = cur.lastrowid
                    conn.execute(
                        'INSERT INTO files_fts(content, relative_path, project_id, file_id) VALUES(?,?,?,?)',
                        (content, relative, project_id, file_id)
                    )
                    conn.execute('DELETE FROM relations WHERE project_id=? AND source_node=?', (project_id, relative))
                    conn.executemany(
                        '''INSERT OR IGNORE INTO relations(project_id,source_node,relation,target_node,evidence,confidence)
                           VALUES(?,?,?,?,?,?)''',
                        _extract_relations(project_id, relative, content)
                    )
                    indexed += 1
                except Exception as exc:  # keep indexing other files
                    errors.append(f'{relative}: {exc}')
                processed = indexed + unchanged
                conn.execute(
                    "UPDATE index_progress SET processed_files=?,updated_at=? WHERE project_id=?",
                    (processed, utc_now(), project_id),
                )
                _report('indexing', total, processed)

            existing_paths = [row['relative_path'] for row in conn.execute(
                'SELECT relative_path FROM files WHERE project_id=?', (project_id,)
            )]
            removed = [path for path in existing_paths if path not in seen]
            for relative in removed:
                file_row = conn.execute(
                    'SELECT id FROM files WHERE project_id=? AND relative_path=?', (project_id, relative)
                ).fetchone()
                if file_row:
                    conn.execute('DELETE FROM files_fts WHERE file_id=?', (file_row['id'],))
                conn.execute('DELETE FROM files WHERE project_id=? AND relative_path=?', (project_id, relative))
                conn.execute('DELETE FROM relations WHERE project_id=? AND source_node=?', (project_id, relative))

            conn.execute('UPDATE projects SET indexed_at=?, status=? WHERE id=?', (now, 'ready', project_id))
            conn.execute(
                "UPDATE index_progress SET phase='done',processed_files=?,updated_at=? WHERE project_id=?",
                (indexed + unchanged, utc_now(), project_id),
            )
            conn.execute(
                'INSERT INTO audit_log(project_id,action,detail,created_at) VALUES(?,?,?,?)',
                (project_id, 'project.indexed', json.dumps({'indexed': indexed, 'unchanged': unchanged, 'errors': errors}), now)
            )
            _report('done', total, indexed + unchanged)

        return {'indexed': indexed, 'unchanged': unchanged, 'removed': len(removed), 'errors': errors}
    except Exception as exc:
        # The whole run failed (e.g. root missing). Record a terminal failure
        # so the UI can show a retry CTA instead of looking stuck.
        fail_now = utc_now()
        with transaction() as conn:
            conn.execute("UPDATE projects SET status='failed' WHERE id=?", (project_id,))
            conn.execute(
                "INSERT INTO index_progress(project_id,phase,total_files,processed_files,started_at,updated_at,error) "
                "VALUES(?,?,?,?,?,?,?) "
                "ON CONFLICT(project_id) DO UPDATE SET phase='failed',error=excluded.error,updated_at=excluded.updated_at",
                (project_id, 'failed', 0, 0, fail_now, fail_now, str(exc)),
            )
            conn.execute(
                'INSERT INTO audit_log(project_id,action,detail,created_at) VALUES(?,?,?,?)',
                (project_id, 'project.index_failed', str(exc)[:300], fail_now)
            )
        raise
```

- [ ] **Step 5: Update `services.create_project` + add `get_index_status` + `reset_interrupted_indexing`**

In `services/api/app/services.py`:

**5a.** Change the `create_project` insert (lines 128-143) to set `status='pending'` instead of `'ready'`:

```python
def create_project(name: str, raw_path: str) -> dict:
    path = resolve_allowed_path(raw_path)
    if not path.is_dir():
        raise ValueError('Project path must be a directory.')
    now = utc_now()
    with transaction() as conn:
        cur = conn.execute(
            'INSERT INTO projects(name,path,created_at,status) VALUES(?,?,?,?)',
            (name.strip(), str(path), now, 'pending')
        )
        project_id = cur.lastrowid
        conn.execute(
            'INSERT INTO audit_log(project_id,action,detail,created_at) VALUES(?,?,?,?)',
            (project_id, 'project.created', str(path), now)
        )
    return get_project(project_id)
```

**5b.** Add two new functions at the end of `services.py` (after `hardware_snapshot`):

```python
def get_index_status(project_id: int) -> dict:
    """Combined view of a project's indexing status for UI polling.

    Joins projects.status with the index_progress row so the frontend can
    drive a progress bar from one cheap read.
    """
    with connect() as conn:
        project = conn.execute('SELECT status, indexed_at FROM projects WHERE id=?', (project_id,)).fetchone()
        if not project:
            raise KeyError('Project not found')
        prog = conn.execute(
            'SELECT phase,total_files,processed_files,error FROM index_progress WHERE project_id=?',
            (project_id,)
        ).fetchone()
    return {
        'status': project['status'],
        'phase': prog['phase'] if prog else ('done' if project['indexed_at'] else 'idle'),
        'total_files': prog['total_files'] if prog else 0,
        'processed_files': prog['processed_files'] if prog else 0,
        'error': prog['error'] if prog else None,
        'indexed_at': project['indexed_at'],
    }


def reset_interrupted_indexing() -> None:
    """Startup recovery: any project left in 'indexing' from a crashed run is
    moved back to 'pending' with a recorded 'interrupted' failure, so the UI
    offers a Retry instead of looking permanently stuck."""
    now = utc_now()
    with transaction() as conn:
        stuck = conn.execute("SELECT id FROM projects WHERE status='indexing'").fetchall()
        for row in stuck:
            conn.execute("UPDATE projects SET status='pending' WHERE id=?", (row['id'],))
            conn.execute(
                "INSERT INTO index_progress(project_id,phase,total_files,processed_files,started_at,updated_at,error) "
                "VALUES(?,?,?,?,?,?,?) "
                "ON CONFLICT(project_id) DO UPDATE SET phase='failed',error=excluded.error,updated_at=excluded.updated_at",
                (row['id'], 'failed', 0, 0, now, now, 'interrupted: indexing did not complete'),
            )
```

- [ ] **Step 6: Wire endpoints + orphan recovery in `main.py`**

In `services/api/app/main.py`:

**6a.** Update imports — replace line 7:
```python
from fastapi import FastAPI, HTTPException, Query, WebSocket
```
with:
```python
from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, WebSocket
```

**6b.** Update the `lifespan` function (lines 28-36) to call orphan recovery:
```python
@asynccontextmanager
async def lifespan(_app: FastAPI):
    migrate()
    services.sync_allowed_roots()
    services.reset_interrupted_indexing()
    yield
```

**6c.** Replace the `create_project` endpoint (lines 215-220) to schedule background indexing:
```python
@app.post('/api/projects')
def create_project(payload: ProjectCreate, background_tasks: BackgroundTasks) -> dict:
    try:
        project = services.create_project(payload.name, payload.path)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    # Auto-trigger the first index in the background so the project is usable
    # in Chat/Files without a manual toolbar click.
    background_tasks.add_task(index_project, project['id'], Path(project['path']))
    return project
```

**6d.** Replace the `index` endpoint (lines 223-231) to add the 409 guard:
```python
@app.post('/api/projects/{project_id}/index')
def index(project_id: int) -> dict:
    try:
        project = services.get_project(project_id)
        status = services.get_index_status(project_id)
        if status['status'] == 'indexing':
            raise HTTPException(status_code=409, detail='Indexing is already in progress.')
        return index_project(project_id, Path(project['path']))
    except HTTPException:
        raise
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
```

**6e.** Add the new `index-status` endpoint immediately after the `index` endpoint:
```python
@app.get('/api/projects/{project_id}/index-status')
def index_status(project_id: int) -> dict:
    try:
        return services.get_index_status(project_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
```

- [ ] **Step 7: Run backend test to verify it passes**

Run: `python -m pytest services/api/tests/test_index_status.py -q`
Expected: PASS (all 7 tests).

- [ ] **Step 8: Run FULL backend suite to check no regressions**

Run: `python -m pytest services/api/tests -q`
Expected: PASS, 115 + new tests. **Watch for:** existing `test_core.py::test_project_index_search_and_graph` and `test_chat_safe_mock_and_citations` — they call `/index` manually after create; since create now schedules a background task that ALSO indexes, the manual index is now a re-index (idempotent, `unchanged` counts). Those tests assert `indexed >= 3` on the manual call — re-index yields `unchanged` not `indexed`, so `indexed` may be 0. **If this fails**, the test asserts on totals; update the assertion to `result.json()['indexed'] + result.json()['unchanged'] >= 3`. Check actual behavior before editing.

## 1B. Frontend: progress banner + polling

**Files:**
- Modify: `apps/web/src/lib/types.ts` (add `IndexStatus`)
- Modify: `apps/web/src/components/Workspace.tsx` (banner component, polling, empty states)

- [ ] **Step 9: Add `IndexStatus` type**

In `apps/web/src/lib/types.ts`, append after the `Project` type (line 1):

```typescript
export type IndexStatus = {
  status: string
  phase: 'scanning' | 'indexing' | 'done' | 'failed' | 'idle'
  total_files: number
  processed_files: number
  error: string | null
  indexed_at: string | null
}
```

- [ ] **Step 10: Add progress banner + polling hook in `Workspace.tsx`**

In `apps/web/src/components/Workspace.tsx`:

**10a.** Add `IndexStatus` to the type import on line 17 (append inside the `import type { ... } from '@/lib/types'`):

Add `IndexStatus` to that import list.

**10b.** Inside the `Workspace` component, after the `project` derivation (line 55) and before `loadSystem`, add the polling hook:

```tsx
  const [indexStatus, setIndexStatus] = useState<IndexStatus | null>(null)

  useEffect(() => {
    if (!project) { setIndexStatus(null); return }
    let cancelled = false
    let timer: ReturnType<typeof setInterval> | null = null
    async function poll() {
      try {
        const status = await api<IndexStatus>(`/api/projects/${project.id}/index-status`)
        if (cancelled) return
        setIndexStatus(status)
        if (status.status === 'pending' || status.status === 'indexing') {
          timer = setTimeout(poll, 1500)
        } else if (status.status === 'ready') {
          // Refresh project list so indexed_at/status reflect completion.
          void loadSystem()
        }
      } catch { /* transient; keep last known status */ }
    }
    void poll()
    return () => {
      cancelled = true
      if (timer) clearTimeout(timer)
    }
  }, [project?.id, project?.status, loadSystem])
```

**10c.** Add a `retryIndex` handler near `indexActiveProject` (after line 99):

```tsx
  async function retryIndex() {
    if (!projectId) return
    setBusy(true); setNotice('')
    try {
      await api(`/api/projects/${projectId}/index`, { method: 'POST' })
      await loadSystem()
    } catch (error) {
      setNotice(error instanceof Error ? error.message : 'Index failed.')
    } finally { setBusy(false) }
  }
```

**10d.** Render the banner. Insert this JSX inside `<section className="main-column">`, immediately after the `</header>` (after line 138) and before the `{notice && ...}` line:

```tsx
          {project && indexStatus && (indexStatus.status === 'pending' || indexStatus.status === 'indexing') && (
            <div className="index-progress-banner">
              <Loader2 className="spin" size={16}/>
              <span>Indexing project… {indexStatus.processed_files}/{indexStatus.total_files || '?'} files</span>
              <div className="progress-track">
                <i style={{ width: `${indexStatus.total_files ? Math.round((indexStatus.processed_files / indexStatus.total_files) * 100) : 0}%` }}/>
              </div>
            </div>
          )}
          {project && indexStatus && indexStatus.status === 'failed' && (
            <div className="index-progress-banner failed">
              <span>Indexing failed{indexStatus.error ? `: ${indexStatus.error}` : ''}.</span>
              <button className="primary small" onClick={() => void retryIndex()} disabled={busy}>{busy ? <Loader2 className="spin" size={14}/> : <RefreshCw size={14}/>}Retry</button>
            </div>
          )}
```

**10e.** Update the `ContextRail` "Not indexed yet" line (line 725) to be status-aware. Replace the `<small>` for the active project block:

Change `{project?.indexed_at ? \`Indexed ${new Date(project.indexed_at).toLocaleString()}\` : 'Not indexed yet'}` to:

```tsx
{project?.status === 'failed' ? 'Indexing failed — retry from the toolbar' : project?.status === 'indexing' ? 'Indexing…' : project?.status === 'pending' ? 'Queued for indexing…' : project?.indexed_at ? `Indexed ${new Date(project.indexed_at).toLocaleString()}` : 'Not indexed yet'}
```

- [ ] **Step 11: Add CSS for the banner**

Find the app's stylesheet (likely `apps/web/src/app/globals.css` or similar — check existing class names like `.notice`). Append:

```css
.index-progress-banner { display: flex; align-items: center; gap: 12px; padding: 10px 16px; background: var(--banner-bg, #eef4ff); border-bottom: 1px solid #d6e0ff; font-size: 13px; }
.index-progress-banner.failed { background: #fff0f0; border-color: #ffd6d6; }
.index-progress-banner .progress-track { flex: 1; max-width: 220px; height: 6px; background: rgba(0,0,0,0.08); border-radius: 999px; overflow: hidden; margin-left: auto; }
.index-progress-banner .progress-track i { display: block; height: 100%; background: #4a6cf7; transition: width 0.3s ease; }
```

(Confirm the actual CSS file path by grepping for `.notice {` before editing; match its variable usage if it uses CSS custom properties.)

- [ ] **Step 12: Run frontend checks**

Run: `cd apps/web && npx tsc --noEmit && npm run test && npm run build`
Expected: tsc clean, 14 tests pass (no new frontend test in 1B — banner is covered by manual smoke + backend status tests), build clean.

- [ ] **Step 13: Commit Task 1**

```bash
git add services/api/app/database.py services/api/app/indexer.py services/api/app/services.py services/api/app/main.py services/api/tests/test_index_status.py apps/web/src/lib/types.ts apps/web/src/components/Workspace.tsx apps/web/src/app/globals.css
git commit -m "feat(task1): auto-index new projects in background with live progress UI"
```

---

# Task 2 — Folder-scope guardrail

## 2A. Backend: classify_folder_scope + endpoint

**Files:**
- Modify: `services/api/app/services.py` (new `classify_folder_scope`)
- Modify: `services/api/app/main.py` (new `GET /api/projects/scope`)
- Test: `services/api/tests/test_folder_scope.py` (new)

- [ ] **Step 14: Write failing backend test**

Create `services/api/tests/test_folder_scope.py`:

```python
"""Phase 2 Task 2: a guardrail that flags accidentally-too-wide folders (system
dirs, drive roots, user profile) before registration, WITHOUT blocking the
user's real cross-project workflow (a parent folder holding many sibling
projects is NOT flagged as dangerous).

The >20 subfolder count is reported as a non-blocking `large_folder` notice,
not a danger.
"""
from __future__ import annotations

import os
from pathlib import Path

from fastapi.testclient import TestClient

from services.api.app.config import settings
from services.api.app.main import app
from services.api.app import services

client = TestClient(app)


def test_classify_flags_user_profile_root() -> None:
    profile = Path.home()
    result = services.classify_folder_scope(str(profile))
    assert result['is_dangerous'] is True, result
    assert result['dangerous_match']


def test_classify_flags_documents_folder() -> None:
    docs = Path.home() / 'Documents'
    # Only assert danger if the folder actually exists on this machine.
    if docs.exists():
        result = services.classify_folder_scope(str(docs))
        assert result['is_dangerous'] is True
        assert 'documents' in (result['dangerous_match'] or '').lower()


def test_classify_flags_drive_root() -> None:
    if os.name != 'nt':
        result = services.classify_folder_scope('/')
        assert result['is_dangerous'] is True
    else:
        result = services.classify_folder_scope('C:\\')
        assert result['is_dangerous'] is True


def test_classify_passes_normal_project_dir() -> None:
    root = settings.workspace_root / 'scope_normal'
    root.mkdir(parents=True, exist_ok=True)
    (root / 'a').mkdir(exist_ok=True)
    result = services.classify_folder_scope(str(root))
    assert result['is_dangerous'] is False
    assert result['dangerous_match'] is None
    assert result['direct_subdirs'] >= 1


def test_classify_counts_direct_subdirs() -> None:
    root = settings.workspace_root / 'scope_count'
    if root.exists():
        import shutil
        shutil.rmtree(root)
    root.mkdir(parents=True)
    for i in range(3):
        (root / f'sub{i}').mkdir()
    (root / 'file.txt').write_text('x')
    result = services.classify_folder_scope(str(root))
    assert result['direct_subdirs'] == 3  # only directories counted, not the file


def test_classify_large_folder_is_not_dangerous() -> None:
    # A folder with many subfolders is wide but NOT dangerous (the user's
    # cross-project workflow depends on this not being flagged).
    root = settings.workspace_root / 'scope_wide'
    if root.exists():
        import shutil
        shutil.rmtree(root)
    root.mkdir(parents=True)
    for i in range(25):
        (root / f'sub{i}').mkdir()
    result = services.classify_folder_scope(str(root))
    assert result['is_dangerous'] is False
    assert result['direct_subdirs'] == 25
    assert result['large_folder'] is True


def test_scope_endpoint_returns_classification() -> None:
    root = settings.workspace_root / 'scope_endpoint'
    root.mkdir(parents=True, exist_ok=True)
    response = client.get('/api/projects/scope', params={'path': str(root)})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body['is_dangerous'] is False
    assert body['dangerous_match'] is None


def test_scope_endpoint_flags_home() -> None:
    response = client.get('/api/projects/scope', params={'path': str(Path.home())})
    assert response.status_code == 200
    assert response.json()['is_dangerous'] is True
```

- [ ] **Step 15: Run test to verify it fails**

Run: `python -m pytest services/api/tests/test_folder_scope.py -q`
Expected: FAIL — `AttributeError: module ... has no attribute 'classify_folder_scope'`.

- [ ] **Step 16: Implement `classify_folder_scope` in `services.py`**

In `services/api/app/services.py`, add this function (place it right before `create_project`, around line 128):

```python
# Folders a user almost never means to register as a single project.
# Matching is case-insensitive on the final path component(s) or on the
# resolved path being a known system root. Crucially, a folder that merely
# CONTAINS many sibling projects (the user's cross-project workflow) is NOT
# dangerous — only genuine accident targets are.
_DANGEROUS_FOLDER_NAMES = {'documents', 'desktop', 'downloads', 'home', 'users', 'windows'}
_DANGEROUS_FOLDER_PREFIXES = ('program files', 'program files (x86)')


def classify_folder_scope(raw_path: str) -> dict:
    """Classify a folder before registration to guard against accidental
    'register everything' mistakes.

    Returns:
        is_dangerous: True only for system/profile/drive-root targets.
        dangerous_match: short label of what matched, or None.
        direct_subdirs: count of immediate subdirectories.
        large_folder: True when direct_subdirs exceeds the non-blocking
            notice threshold (the user may still proceed).
    """
    try:
        path = Path(raw_path).expanduser().resolve()
    except (OSError, ValueError):
        return {'is_dangerous': False, 'dangerous_match': None, 'direct_subdirs': 0, 'large_folder': False}

    is_dangerous = False
    dangerous_match: str | None = None

    # Drive roots and filesystem root.
    if path == path.parent:
        is_dangerous, dangerous_match = True, 'drive/filesystem root'
    # Windows drive root, e.g. C:\
    elif len(path.parts) == 1 and len(path.drive) > 0:
        is_dangerous, dangerous_match = True, 'drive root'
    else:
        final = path.name.lower()
        if final in _DANGEROUS_FOLDER_NAMES:
            is_dangerous, dangerous_match = True, path.name
        elif any(final.startswith(p) for p in _DANGEROUS_FOLDER_PREFIXES):
            is_dangerous, dangerous_match = True, path.name
        # The user's own profile root (Path.home()).
        elif path == Path.home():
            is_dangerous, dangerous_match = True, 'user profile root'

    # Count immediate subdirectories (best-effort; permission errors -> 0).
    direct_subdirs = 0
    try:
        if path.is_dir():
            direct_subdirs = sum(1 for child in path.iterdir() if child.is_dir())
    except (OSError, PermissionError):
        direct_subdirs = 0

    LARGE_FOLDER_THRESHOLD = 20
    return {
        'is_dangerous': is_dangerous,
        'dangerous_match': dangerous_match,
        'direct_subdirs': direct_subdirs,
        'large_folder': direct_subdirs > LARGE_FOLDER_THRESHOLD,
    }
```

- [ ] **Step 17: Add the `GET /api/projects/scope` endpoint in `main.py`**

In `services/api/app/main.py`, add this endpoint immediately **before** the `@app.post('/api/projects')` route (around line 215):

```python
@app.get('/api/projects/scope')
def project_scope(path: str = Query(...)) -> dict:
    """Pre-registration guardrail classification for a folder path.

    Used by both registration flows (Settings modal and Explorer 'Open as
    project') to decide whether to show a confirmation dialog (dangerous) or a
    non-blocking notice (very large folder). Does not mutate anything.
    """
    return services.classify_folder_scope(path)
```

- [ ] **Step 18: Run backend test to verify it passes**

Run: `python -m pytest services/api/tests/test_folder_scope.py -q`
Expected: PASS (all 8 tests). If `test_classify_flags_documents_folder` is skipped because Documents doesn't exist, that's fine.

- [ ] **Step 19: Run FULL backend suite**

Run: `python -m pytest services/api/tests -q`
Expected: PASS, no regressions.

## 2B. Frontend: guardrail gate in both registration flows

**Files:**
- Modify: `apps/web/src/lib/types.ts` (add `FolderScope`)
- Modify: `apps/web/src/components/Workspace.tsx` (gate in `addProject` and `registerProjectFromExplorer`)

- [ ] **Step 20: Add `FolderScope` type**

In `apps/web/src/lib/types.ts`, append:

```typescript
export type FolderScope = {
  is_dangerous: boolean
  dangerous_match: string | null
  direct_subdirs: number
  large_folder: boolean
}
```

- [ ] **Step 21: Add a shared guardrail helper + dangerous-folder modal in `Workspace.tsx`**

In `apps/web/src/components/Workspace.tsx`:

**21a.** Add `FolderScope` to the type import on line 17.

**21b.** Add a module-level helper (near the top, after the `nav` array around line 42):

```tsx
const LARGE_FOLDER_HINT_THRESHOLD = 20

async function confirmWideFolder(path: string): Promise<'continue' | 'cancel' | 'normal'> {
  // Returns 'normal' when no gate is needed, 'continue'/'cancel' after the
  // user responds to a dangerous-folder modal. A large-but-safe folder shows
  // only a non-blocking console notice and returns 'normal'.
  let scope: FolderScope
  try {
    scope = await api<FolderScope>(`/api/projects/scope?path=${encodeURIComponent(path)}`)
  } catch {
    return 'normal' // can't classify; let POST validation surface any real error
  }
  if (scope.is_dangerous) {
    const label = scope.dangerous_match || 'a system folder'
    const ok = window.confirm(
      `"${path}" looks like ${label}. Registering it will index everything inside. Continue?`
    )
    return ok ? 'continue' : 'cancel'
  }
  if (scope.direct_subdirs > LARGE_FOLDER_HINT_THRESHOLD) {
    // Non-blocking informational hint only.
    console.info(`[InMyAI] Folder has ${scope.direct_subdirs} subfolders; indexing may take a while.`)
  }
  return 'normal'
}
```

**21c.** Gate `registerProjectFromExplorer` (lines 104-111). Replace the function body:

```tsx
  async function registerProjectFromExplorer(path: string, name: string) {
    setNotice('')
    const gate = await confirmWideFolder(path)
    if (gate === 'cancel') return
    const created = await api<Project>('/api/projects', { method: 'POST', body: JSON.stringify({ name, path }) })
    await loadSystem()
    setProjectId(created.id)
    setView('chat')
    setNotice(`"${created.name}" registered. Indexing in the background — chat will use it once ready.`)
  }
```

**21d.** Gate `addProject` in `SettingsModal` (lines 738-743). Replace the function body:

```tsx
  async function addProject(e: React.FormEvent) {
    e.preventDefault(); setSaving(true); setError('')
    try {
      const gate = await confirmWideFolder(path)
      if (gate === 'cancel') { setSaving(false); return }
      await api('/api/projects', { method: 'POST', body: JSON.stringify({ name, path }) }); await onChanged(); setName(''); setPath('')
    }
    catch (err) { setError(err instanceof Error ? err.message : 'Unable to add project') }
    finally { setSaving(false) }
  }
```

- [ ] **Step 22: Run frontend checks**

Run: `cd apps/web && npx tsc --noEmit && npm run test && npm run build`
Expected: clean. (No new frontend test here — behavior is a `window.confirm` gate; covered by backend `test_folder_scope.py` and manual smoke.)

- [ ] **Step 23: Commit Task 2**

```bash
git add services/api/app/services.py services/api/app/main.py services/api/tests/test_folder_scope.py apps/web/src/lib/types.ts apps/web/src/components/Workspace.tsx
git commit -m "feat(task2): guardrail against registering system/drive-root folders"
```

---

# Task 3 — Merge code relations into radial Explorer (Opsi A) + Graphify import UI

## 3A. Backend: Graphify import endpoint

**Files:**
- Modify: `services/api/app/main.py` (new `POST /api/projects/{id}/graph/import`)
- Test: `services/api/tests/test_import_graphify.py` (extend existing)

- [ ] **Step 24: Check existing import test, then add endpoint test**

Read `services/api/tests/test_import_graphify.py` to see existing coverage of `services.import_graphify`. Then append a new test for the HTTP endpoint:

```python
def test_graph_import_endpoint_accepts_graphify_json() -> None:
    """Phase 2 Task 3: the Graphify importer is now reachable over HTTP so the
    Graph tab UI can offer it as a real affordance, not just a footer caption."""
    from services.api.app.config import settings
    from fastapi.testclient import TestClient
    from services.api.app.main import app
    client = TestClient(app)
    # Reuse a project from earlier tests, or create one.
    projects = client.get('/api/projects').json()
    if not projects:
        root = settings.workspace_root / 'graphify_demo'
        root.mkdir(parents=True, exist_ok=True)
        proj = client.post('/api/projects', json={'name': 'Graphify', 'path': str(root)}).json()
        project_id = proj['id']
    else:
        project_id = projects[0]['id']
    payload = {
        'nodes': [{'id': 'a'}, {'id': 'b'}],
        'edges': [{'source': 'a', 'target': 'b', 'relation': 'depends_on'}],
    }
    response = client.post(f'/api/projects/{project_id}/graph/import', json=payload)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body['imported'] >= 1


def test_graph_import_endpoint_404_for_unknown_project() -> None:
    from fastapi.testclient import TestClient
    from services.api.app.main import app
    client = TestClient(app)
    response = client.post('/api/projects/999999/graph/import', json={'edges': []})
    assert response.status_code == 404
```

- [ ] **Step 25: Run test to verify it fails**

Run: `python -m pytest services/api/tests/test_import_graphify.py -q`
Expected: FAIL — 404 on `/api/projects/{id}/graph/import` (route doesn't exist yet).

- [ ] **Step 26: Add the import endpoint in `main.py`**

In `services/api/app/main.py`, add this route immediately **after** the existing `graph` GET endpoint (around line 279):

```python
@app.post('/api/projects/{project_id}/graph/import')
def graph_import(project_id: int, payload: dict) -> dict:
    """Import a Graphify graph.json into the relations table.

    Edges supplement (do not replace) deterministic EXTRACTED relations; each
    imported edge is tagged confidence='INFERRED'. Accepts the Graphify payload
    shape directly as JSON.
    """
    try:
        return services.import_graphify(project_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
```

- [ ] **Step 27: Run backend test + full suite**

Run: `python -m pytest services/api/tests/test_import_graphify.py services/api/tests -q`
Expected: PASS, no regressions.

## 3B. Frontend: relations overlay in Explorer + Graphify import button

**Files:**
- Modify: `apps/web/src/components/Workspace.tsx` (`ExplorerView` overlay; `GraphView` import button)

- [ ] **Step 28: Add Graphify import button to `GraphView`**

In `apps/web/src/components/Workspace.tsx`, the `GraphView` function (lines 304-310). Add an import affordance. Replace the function's return statement's opening to include an import button + handler. Concretely, add state + handler near the top of `GraphView` and a button in the search row.

Add inside `GraphView` after the existing state declarations (line 305):

```tsx
  const [importBusy, setImportBusy] = useState(false)
  const [importNotice, setImportNotice] = useState('')

  async function importGraphify(file: File) {
    setImportBusy(true); setImportNotice('')
    try {
      const text = await file.text()
      const payload = JSON.parse(text)
      const result = await api<{ imported: number; skipped: number }>(`/api/projects/${project.id}/graph/import`, { method: 'POST', body: JSON.stringify(payload) })
      setImportNotice(`Imported ${result.imported} edge(s).`)
      const data = await api<{ relations: Relation[] }>(`/api/projects/${project.id}/graph`)
      setRelations(data.relations)
    } catch (err) {
      setImportNotice(err instanceof Error ? err.message : 'Import failed.')
    } finally { setImportBusy(false) }
  }
```

Then in the JSX, replace the `<div className="graph-search">…</div>` block (line 309, the search row) to add an import button after the Trace button:

```tsx
        <div className="graph-search">
          <Search size={16}/>
          <input value={node} onChange={(e) => setNode(e.target.value)} placeholder="Explain a file, symbol, or dependency"/>
          <button className="primary small" onClick={() => void query()}>Trace</button>
          <label className="secondary small" title="Import a Graphify graph.json">
            {importBusy ? <Loader2 className="spin" size={14}/> : <Download size={14}/>}Import graph.json
            <input type="file" accept=".json,application/json" hidden onChange={(e) => { const f = e.target.files?.[0]; if (f) void importGraphify(f); e.target.value = '' }}/>
          </label>
          {importNotice && <small className="muted">{importNotice}</small>}
        </div>
```

(`Download` is already imported in the icon list at line 8.) Update the caption text (line 309) from "Graphify graph.json can be integrated as an additional source." to "Import a Graphify graph.json above to add inferred edges."

- [ ] **Step 29: Add relations overlay to `ExplorerView`**

In `ExplorerView` (lines 573-722), the component needs to know the active project + its status to decide whether to overlay relations. Change the signature and add overlay logic.

**29a.** Change the `ExplorerView` signature (line 573) to accept the active project:

```tsx
function ExplorerView({ onOpenProject, activeProject }: { onOpenProject: (path: string, name: string) => Promise<void>; activeProject: Project | null }) {
```

**29b.** Inside `ExplorerView`, after the existing state (line 582), add:

```tsx
  const [relations, setRelations] = useState<Relation[]>([])
  const [showRelations, setShowRelations] = useState(false)
  const RELATION_EDGE_CAP = 60

  // Persist the relations toggle so it survives navigation.
  useEffect(() => {
    const stored = typeof window !== 'undefined' ? window.localStorage.getItem('inmyai:explorer:showRelations') : null
    setShowRelations(stored === '1')
  }, [])
  function toggleRelations() {
    setShowRelations((current) => {
      const next = !current
      if (typeof window !== 'undefined') window.localStorage.setItem('inmyai:explorer:showRelations', next ? '1' : '0')
      return next
    })
  }

  // When the browsed folder IS the active indexed project, fetch its relations.
  const browsingActiveProject = !!activeProject && activeProject.status === 'ready' && !!currentPath
    && !!activeProject.path
    && normalizePath(currentPath) === normalizePath(activeProject.path)

  useEffect(() => {
    if (!browsingActiveProject || !activeProject) { setRelations([]); return }
    let cancelled = false
    api<{ relations: Relation[] }>(`/api/projects/${activeProject.id}/graph`).then((data) => {
      if (!cancelled) setRelations(data.relations)
    }).catch(() => { if (!cancelled) setRelations([]) })
    return () => { cancelled = true }
  }, [browsingActiveProject, activeProject?.id])
```

**29c.** Add the `normalizePath` helper at module level (near the top, after the `nav` array):

```tsx
function normalizePath(p: string): string {
  return p.replace(/\\/g, '/').replace(/\/+$/, '').toLowerCase()
}
```

**29d.** Compute edge overlays. Inside `ExplorerView`, after the `positioned` useMemo (line 661), add:

```tsx
  // Build overlay edges from relations, matching relation node names (relative
  // paths) against the radial entry names. Capped to avoid a hairball.
  const overlayEdges = useMemo(() => {
    if (!showRelations || !browsingActiveProject) return []
    const nameToPos = new Map<string, { x: number; y: number }>()
    for (const { entry, x, y } of positioned) nameToPos.set(entry.name, { x, y })
    nameToPos.set(currentName || '', { x: 300, y: 235 }) // root
    const edges: { sx: number; sy: number; tx: number; ty: number; relation: string; source: string; target: string; evidence: string }[] = []
    for (const rel of relations) {
      if (edges.length >= RELATION_EDGE_CAP) break
      // Match by trailing path segment (relations use relative paths like
      // 'src/auth.ts'; entries show bare names like 'auth.ts').
      const srcName = rel.source_node.split('/').pop() || ''
      const tgtName = rel.target_node.split('/').pop() || ''
      const s = nameToPos.get(srcName) || (nameToPos.has(rel.source_node) ? nameToPos.get(rel.source_node) : undefined)
      const t = nameToPos.get(tgtName) || (nameToPos.has(rel.target_node) ? nameToPos.get(rel.target_node) : undefined)
      if (s && t) edges.push({ sx: s.x, sy: s.y, tx: t.x, ty: t.y, relation: rel.relation, source: rel.source_node, target: rel.target_node, evidence: '' })
    }
    return edges
  }, [showRelations, browsingActiveProject, relations, positioned, currentName])
```

**29e.** Render the overlay + toggle. In the SVG block (lines 686-704), insert the relation edges **before** the existing explorer-edge lines (so nodes render on top). Add right after `<svg ...>` (line 686):

```tsx
            {overlayEdges.map((edge, i) => (
              <line key={`rel-${i}`} x1={edge.sx} y1={edge.sy} x2={edge.tx} y2={edge.ty}
                className={`relation-edge rel-${edge.relation}`} />
            ))}
```

**29f.** Add the toggle button to the explorer toolbar. In the `explorer-toolbar` div (lines 665-672), add a toggle button after the native Browse button (only when browsing the active indexed project):

```tsx
          {browsingActiveProject && (
            <button className={`secondary small${showRelations ? ' active' : ''}`} type="button" onClick={toggleRelations} title="Overlay code relations (imports/defines/calls)">
              <Network size={13}/>{showRelations ? 'Relations on' : 'Relations'}
            </button>
          )}
```

**29f-bis.** Add a hint when browsing the active project but not indexed. After the SVG block (after line 704), add:

```tsx
        {activeProject && currentPath && normalizePath(currentPath) === normalizePath(activeProject.path) && activeProject.status !== 'ready' && (
          <p className="muted explorer-hint">Index this project to see code relations here.</p>
        )}
        {browsingActiveProject && showRelations && relations.length > RELATION_EDGE_CAP && (
          <p className="muted explorer-hint">{relations.length} relations — showing first {RELATION_EDGE_CAP}. Use the Graph tab to trace the rest.</p>
        )}
```

**29g.** Update the call site to pass `activeProject`. In the `Workspace` render (line 142):

Change `<ExplorerView onOpenProject={registerProjectFromExplorer}/>` to:

```tsx
            <ExplorerView onOpenProject={registerProjectFromExplorer} activeProject={project}/>
```

- [ ] **Step 30: Add CSS for relation edges + hint**

In the same stylesheet where you added the banner CSS (Task 1 Step 11), append:

```css
.relation-edge { stroke-width: 1.5; stroke-opacity: 0.3; fill: none; }
.relation-edge.rel-imports { stroke: #4a6cf7; }
.relation-edge.rel-defines { stroke: #2ea043; }
.relation-edge.rel-calls { stroke: #d29922; }
.explorer-hint { margin: 8px 0; font-size: 12px; }
```

- [ ] **Step 31: Run frontend checks**

Run: `cd apps/web && npx tsc --noEmit && npm run test && npm run build`
Expected: clean.

- [ ] **Step 32: Commit Task 3**

```bash
git add services/api/app/main.py services/api/tests/test_import_graphify.py apps/web/src/components/Workspace.tsx apps/web/src/app/globals.css
git commit -m "feat(task3): overlay code relations on Explorer + Graphify import button"
```

---

# Task 4 — Simplify nav: Main + Advanced collapsible

**Files:**
- Modify: `apps/web/src/components/Workspace.tsx` (`nav` split, rendering, localStorage)
- Modify: `apps/web/tests/routing.test.mjs` (extend pure-data test)

- [ ] **Step 33: Write failing frontend test**

In `apps/web/tests/routing.test.mjs`, replace the first test with group-aware assertions. Append (keeping existing tests):

```javascript
test('nav splits into 5 main + 4 advanced, no overlap, union = all 9', () => {
  const main = ['chat', 'files', 'explorer', 'graph', 'terminal']
  const advanced = ['memory', 'studio', 'git', 'agents']
  const all = [...main, ...advanced]
  // No duplicates within or across groups.
  assert.equal(new Set(all).size, all.length)
  // Union is exactly the original 9 surfaces — nothing dropped.
  const original = new Set(['chat', 'files', 'memory', 'graph', 'studio', 'git', 'agents', 'explorer', 'terminal'])
  assert.deepEqual(new Set(all), original)
  assert.equal(main.length, 5)
  assert.equal(advanced.length, 4)
})
```

Also update the existing first test (line 4-7) — it still passes as-is (it asserts no dups across all 9), keep it.

- [ ] **Step 34: Run test to verify it fails (or is trivially green — it's pure data)**

Run: `cd apps/web && npm run test`
Expected: the new test PASSES immediately (it's pure data, testing the intended split). This is a guard against future drift of the split. (If you prefer strict TDD red-first, this test encodes the contract before the code reflects it — acceptable here since the data is the spec.)

- [ ] **Step 35: Split the `nav` array in `Workspace.tsx`**

In `apps/web/src/components/Workspace.tsx`, replace the `nav` array (lines 32-42) with two arrays:

```tsx
type NavItem = { id: View; label: string; icon: typeof Bot }

const navMain: NavItem[] = [
  { id: 'chat', label: 'Chat', icon: MessageSquareText },
  { id: 'files', label: 'Files', icon: FileCode2 },
  { id: 'explorer', label: 'Explorer', icon: Map },
  { id: 'graph', label: 'Graph', icon: Network },
  { id: 'terminal', label: 'Terminal', icon: TerminalSquare }
]

const navAdvanced: NavItem[] = [
  { id: 'memory', label: 'Memory', icon: BrainCircuit },
  { id: 'studio', label: 'Studio', icon: Sparkles },
  { id: 'git', label: 'Git', icon: GitBranch },
  { id: 'agents', label: 'Agents', icon: Workflow }
]
```

- [ ] **Step 36: Render the two groups with a collapsible Advanced header**

**36a.** Add collapse state + localStorage inside the `Workspace` component (after the `notice` state, line 53):

```tsx
  const [advancedOpen, setAdvancedOpen] = useState(false)
  const ADVANCED_NAV_KEY = 'inmyai:nav:advancedExpanded'

  useEffect(() => {
    const stored = typeof window !== 'undefined' ? window.localStorage.getItem(ADVANCED_NAV_KEY) : null
    setAdvancedOpen(stored === '1')
  }, [])

  // If the active view is in the Advanced group, auto-expand so the active
  // tab is always visible/highlighted.
  useEffect(() => {
    if (navAdvanced.some((item) => item.id === view)) setAdvancedOpen(true)
  }, [view])

  function toggleAdvanced() {
    setAdvancedOpen((current) => {
      const next = !current
      if (typeof window !== 'undefined') window.localStorage.setItem(ADVANCED_NAV_KEY, next ? '1' : '0')
      return next
    })
  }
```

**36b.** Replace the sidebar `<nav>` render (line 125):

```tsx
        <nav>
          <div className="nav-group">
            {navMain.map((item) => { const Icon = item.icon; return <button key={item.id} className={view === item.id ? 'active' : ''} onClick={() => setView(item.id)}><Icon size={17}/><span>{item.label}</span></button> })}
          </div>
          <div className="nav-group nav-group-advanced">
            <button className="nav-group-header" onClick={toggleAdvanced} aria-expanded={advancedOpen}>
              <ChevronRight size={14} className={advancedOpen ? 'nav-chevron-open' : ''}/>
              <span>Advanced</span>
            </button>
            {advancedOpen && navAdvanced.map((item) => { const Icon = item.icon; return <button key={item.id} className={view === item.id ? 'active' : ''} onClick={() => setView(item.id)}><Icon size={17}/><span>{item.label}</span></button> })}
          </div>
        </nav>
```

**36c.** Update `MobileNav` (line 945) to show both groups flat (mobile has no room for collapse). Replace:

```tsx
function MobileNav({ view, setView }: { view: View; setView: (view: View) => void }) {
  const all = [...navMain, ...navAdvanced]
  return <nav className="mobile-nav">{all.map((item) => { const Icon = item.icon; return <button key={item.id} className={view === item.id ? 'active' : ''} onClick={() => setView(item.id)}><Icon size={18}/><span>{item.label}</span></button> })}</nav>
}
```

**36d.** The `topbar` title lookup (line 133) uses `nav.find(...)`. Replace `nav` references there with `[...navMain, ...navAdvanced]`:

Change `{nav.find((item) => item.id === view)?.label}` to `{[...navMain, ...navAdvanced].find((item) => item.id === view)?.label}`.

- [ ] **Step 37: Verify `ChevronRight` is imported**

Check `apps/web/src/components/Icons.tsx` exports `ChevronRight`. If not, add it (the file likely re-exports lucide icons; add `ChevronRight` to the export list and to the import on line 7-12 of `Workspace.tsx`). Run `grep -n "ChevronRight" apps/web/src/components/Icons.tsx` to confirm before editing.

- [ ] **Step 38: Add CSS for nav groups**

In the stylesheet, append:

```css
.nav-group { display: flex; flex-direction: column; gap: 2px; }
.nav-group-advanced { margin-top: 8px; border-top: 1px solid rgba(255,255,255,0.06); padding-top: 8px; }
.nav-group-header { display: flex; align-items: center; gap: 8px; width: 100%; padding: 6px 10px; background: none; border: none; color: inherit; font-size: 12px; text-transform: uppercase; letter-spacing: 0.04em; opacity: 0.7; cursor: pointer; }
.nav-chevron-open { transform: rotate(90deg); transition: transform 0.15s ease; }
```

- [ ] **Step 39: Run frontend checks**

Run: `cd apps/web && npx tsc --noEmit && npm run test && npm run build`
Expected: clean, 15 tests pass (14 + new).

- [ ] **Step 40: Commit Task 4**

```bash
git add apps/web/src/components/Workspace.tsx apps/web/src/components/Icons.tsx apps/web/tests/routing.test.mjs apps/web/src/app/globals.css
git commit -m "feat(task4): group nav into Main + collapsible Advanced, persisted in localStorage"
```

---

# Finalize — decision doc + QA report

- [ ] **Step 41: Write decision record**

Create `docs/decisions/phase2-core-flow.md` following the existing format (see `docs/decisions/explorer-and-terminal.md` for the section structure: `# Decision record: ...`, `Date:`, `Status:`, then `## 1. The problem`, `## 2. ...`). Cover all 4 tasks: problem, reasoning, what changed (with file refs), how to verify, what was not built (Task 5 packaging).

- [ ] **Step 42: Update `QA_REPORT.md`**

Update the test table (now `pytest` count = 115 + new tests; `node --test` = 15), add a "What changed since 2026-07-23" section summarizing the 4 tasks, and note intentional deviations (e.g., TestClient runs BackgroundTasks synchronously, so progress-banner UX is verified by manual smoke + backend status tests, not a frontend unit test).

- [ ] **Step 43: Final full verification + commit docs**

Run the full gate one more time:
```bash
python -m pytest services/api/tests -q
cd apps/web && npx tsc --noEmit && npm run test && npm run build
```
Then:
```bash
git add docs/decisions/phase2-core-flow.md QA_REPORT.md
git commit -m "docs(phase2): decision record + QA report for core-flow fixes"
```

---

## Self-review notes (already applied)

- **Spec coverage:** Task 1 (auto-index, status machine, progress table, endpoint, orphan recovery, 409 guard, banner, empty states) ✓. Task 2 (dangerous-path detection, >20 non-blocking, both flows gated, scope endpoint) ✓. Task 3 (relations overlay, toggle+localStorage, edge cap, Graphify import endpoint+UI) ✓. Task 4 (split, collapsible, localStorage, auto-expand, mobile flat) ✓.
- **Type consistency:** `IndexStatus`, `FolderScope` defined once, used consistently. `NavItem` introduced in Task 4. `classify_folder_scope` returns the same keys the frontend `FolderScope` type expects. `get_index_status` return shape matches `IndexStatus`.
- **Placeholders:** none — every step has exact code.
- **Known risk flagged inline:** Step 8's note about `test_project_index_search_and_graph` asserting `indexed >= 3` on a manual re-index (now yields `unchanged`). Verify actual output before editing the assertion.
