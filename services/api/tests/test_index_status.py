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
    assert project['status'] in ('pending', 'ready')
    fetched = client.get('/api/projects').json()
    this = next(p for p in fetched if p['id'] == project['id'])
    assert this['status'] == 'ready'
    assert this['indexed_at'] is not None


def test_index_status_endpoint_reports_progress_and_done() -> None:
    root = _fresh_project_dir('idx_status')
    project = client.post('/api/projects', json={'name': 'IdxStatus', 'path': str(root)}).json()
    status = client.get(f"/api/projects/{project['id']}/index-status").json()
    assert status['status'] == 'ready'
    assert status['phase'] == 'done'
    assert status['total_files'] >= 1
    assert status['processed_files'] >= 1
    assert status['processed_files'] <= status['total_files']


def test_index_status_404_for_unknown_project() -> None:
    response = client.get('/api/projects/999999/index-status')
    assert response.status_code == 404


def test_double_index_returns_409_when_already_indexing() -> None:
    root = _fresh_project_dir('idx_double')
    project = client.post('/api/projects', json={'name': 'IdxDouble', 'path': str(root)}).json()
    from services.api.app.database import transaction
    with transaction() as conn:
        conn.execute("UPDATE projects SET status='indexing' WHERE id=?", (project['id'],))
    response = client.post(f"/api/projects/{project['id']}/index")
    assert response.status_code == 409
    assert 'already' in response.json()['detail'].lower()


def test_failed_indexing_records_error_status() -> None:
    root = _fresh_project_dir('idx_fail')
    project = client.post('/api/projects', json={'name': 'IdxFail', 'path': str(root)}).json()
    import shutil
    shutil.rmtree(root)
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
    with transaction() as conn:
        conn.execute("UPDATE projects SET status='indexing' WHERE id=?", (project['id'],))
    svc.reset_interrupted_indexing()
    fetched = next(p for p in client.get('/api/projects').json() if p['id'] == project['id'])
    assert fetched['status'] == 'pending'
    status = client.get(f"/api/projects/{project['id']}/index-status").json()
    assert status['phase'] == 'failed'
    assert 'interrupted' in (status['error'] or '').lower()


def test_indexing_status_is_observable_mid_run_from_another_connection() -> None:
    """Regression guard: the 'indexing' state transition and progress counts
    MUST be committed in their own short transactions (not held inside one big
    uncommitted transaction) so a separate connection — the /index-status
    reader and the 409 double-index guard — can observe them WHILE indexing
    runs.

    Under SQLite WAL, an uncommitted write is invisible to other connections.
    This test runs index_project in a real background thread with a
    progress_cb barrier, then reads the status from the main thread (a
    different connection) mid-run and asserts it sees 'indexing' with a
    non-final phase.
    """
    import threading
    from services.api.app.database import connect
    from services.api.app.indexer import index_project

    # A folder with enough files to exceed one progress-commit batch (25),
    # so the indexing thread is reliably still running when we sample.
    root = _fresh_project_dir('idx_observable')
    for i in range(60):
        (root / f'f{i}.py').write_text(f'x{i} = {i}\n', encoding='utf-8')

    project = client.post('/api/projects', json={'name': 'IdxObservable', 'path': str(root)}).json()

    barrier = threading.Event()
    sampled: dict = {}

    def progress_cb(phase: str, total: int, processed: int) -> None:
        # On the first 'indexing' progress report, let the main thread sample.
        if phase == 'indexing' and not barrier.is_set():
            with connect() as conn:
                row = conn.execute(
                    'SELECT status FROM projects WHERE id=?', (project['id'],)
                ).fetchone()
                prog = conn.execute(
                    'SELECT phase, total_files FROM index_progress WHERE project_id=?',
                    (project['id'],)
                ).fetchone()
            sampled['status'] = row['status'] if row else None
            sampled['phase'] = prog['phase'] if prog else None
            sampled['total'] = prog['total_files'] if prog else 0
            barrier.set()

    thread = threading.Thread(
        target=index_project, args=(project['id'], root), kwargs={'progress_cb': progress_cb}
    )
    thread.start()
    # Wait until the progress_cb has sampled the mid-run state (timeout guard).
    assert barrier.wait(timeout=30), 'progress_cb was never invoked'
    thread.join(timeout=30)
    assert not thread.is_alive(), 'index_project did not finish'

    # The sample taken from a DIFFERENT connection mid-run must reflect the
    # committed 'indexing' transition, not the stale pre-index value.
    assert sampled['status'] == 'indexing', sampled
    assert sampled['phase'] == 'indexing', sampled
    assert sampled['total'] >= 60, sampled
    # And the project must end up 'ready' after the thread finishes.
    final = next(p for p in client.get('/api/projects').json() if p['id'] == project['id'])
    assert final['status'] == 'ready'


def test_registering_an_already_registered_path_returns_existing_project() -> None:
    """Bug found via real Explorer use: clicking "Open as project" on a
    folder that's already registered used to bubble a raw
    'UNIQUE constraint failed: projects.path' SQLite error to the UI.
    Re-registering the same path must instead just return the existing
    project, unchanged, with no duplicate row and no error."""
    root = _fresh_project_dir('idx_dup')
    first = client.post('/api/projects', json={'name': 'IdxDup', 'path': str(root)})
    assert first.status_code == 200, first.text
    first_project = first.json()

    second = client.post('/api/projects', json={'name': 'IdxDupAgain', 'path': str(root)})
    assert second.status_code == 200, second.text
    second_project = second.json()

    assert second_project['id'] == first_project['id']
    # The original name is preserved - re-registering doesn't rename it.
    assert second_project['name'] == first_project['name']

    all_projects = client.get('/api/projects').json()
    matching = [p for p in all_projects if p['path'] == first_project['path']]
    assert len(matching) == 1, 'duplicate registration must not create a second row'


def test_legacy_ready_project_without_indexed_at_is_backfilled_to_pending() -> None:
    """Bug found via real use: a project row inserted before auto-indexing
    existed defaults to status='ready' with indexed_at IS NULL - a state the
    current code never revisits on its own, so it stays permanently
    unindexed. migrate()'s compatibility backfill must requeue it as
    'pending', and list_projects_needing_index() must then pick it up."""
    from services.api.app.database import migrate, transaction
    from services.api.app import services as svc

    root = _fresh_project_dir('idx_legacy')
    now = '2020-01-01T00:00:00+00:00'
    with transaction() as conn:
        cur = conn.execute(
            "INSERT INTO projects(name,path,created_at,status) VALUES(?,?,?,'ready')",
            ('IdxLegacy', str(root), now),
        )
        legacy_id = cur.lastrowid

    # Before migrate() runs again, the row is still (incorrectly) 'ready'.
    fetched = next(p for p in client.get('/api/projects').json() if p['id'] == legacy_id)
    assert fetched['status'] == 'ready'
    assert fetched['indexed_at'] is None

    migrate()  # idempotent - safe to call again, this is what re-runs on every startup

    fetched = next(p for p in client.get('/api/projects').json() if p['id'] == legacy_id)
    assert fetched['status'] == 'pending'

    needing = svc.list_projects_needing_index()
    assert any(p['id'] == legacy_id for p in needing)


def test_migrate_backfill_does_not_touch_already_indexed_projects() -> None:
    """The backfill must be scoped to indexed_at IS NULL specifically - a
    normally-completed project (status='ready', indexed_at set) must not be
    reset to 'pending' every time migrate() runs, or it would be
    re-indexed on every single app startup for no reason."""
    from services.api.app.database import migrate

    root = _fresh_project_dir('idx_already_done')
    project = client.post('/api/projects', json={'name': 'IdxDone', 'path': str(root)}).json()
    fetched = next(p for p in client.get('/api/projects').json() if p['id'] == project['id'])
    assert fetched['status'] == 'ready'
    assert fetched['indexed_at'] is not None

    migrate()

    fetched_again = next(p for p in client.get('/api/projects').json() if p['id'] == project['id'])
    assert fetched_again['status'] == 'ready'
