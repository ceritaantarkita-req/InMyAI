"""Tests for the Settings-UI-managed allowed roots (GET/POST/DELETE
/api/settings/allowed-roots).

Why this exists: previously the only way to let InMyAI open a project
outside `./workspace` was hand-editing `INMYAI_ALLOWED_ROOTS` in `.env` and
restarting the server - fine for one developer, impractical for anyone else
InMyAI ships to. These endpoints let a root be added/removed from the UI at
runtime, with the change taking effect immediately (no restart), while
still respecting the sensitive-path blocklist and never touching `.env`
itself (so the static, deploy-time configuration stays authoritative and
`.env` never gets rewritten by the running app).

Deliberately does NOT use pytest's `tmp_path` (same reasoning as
test_browse.py: it lives under Windows' AppData, which the blocklist
rejects). Scratch folders live under settings.workspace_root's parent
instead, matching test_browse.py's convention for "a folder genuinely
outside the workspace."
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from services.api.app import services
from services.api.app.config import settings
from services.api.app.database import connect, transaction
from services.api.app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def _clear_allowed_roots_table():
    """Each test in this file gets a clean `allowed_roots` table and a
    freshly-synced `settings.allowed_roots`, so tests can't leak dynamic
    roots into one another via the shared session DB (see conftest.py)."""
    with transaction() as conn:
        conn.execute('DELETE FROM allowed_roots')
    services.sync_allowed_roots()
    yield
    with transaction() as conn:
        conn.execute('DELETE FROM allowed_roots')
    services.sync_allowed_roots()


@pytest.fixture()
def outside_folder(request: pytest.FixtureRequest) -> Path:
    # Unique per test: several tests in this file register a project against
    # this folder, and `projects.path` is UNIQUE - reusing one fixed path
    # across tests in the same session DB (see conftest.py) would collide.
    safe_name = request.node.name.replace('[', '_').replace(']', '_')
    folder = settings.workspace_root.parent / f'allowed-roots-scratch-{safe_name}'
    folder.mkdir(parents=True, exist_ok=True)
    yield folder
    with transaction() as conn:
        conn.execute('DELETE FROM projects WHERE path LIKE ?', (f'{folder.resolve()}%',))


@pytest.fixture()
def strict_roots():
    """Temporarily turn off the test session's blanket
    `allow_any_local_path = True` (set in conftest.py for every other test)
    so the allowed-roots check actually has teeth for this test."""
    saved = settings.allow_any_local_path
    settings.allow_any_local_path = False
    try:
        yield
    finally:
        settings.allow_any_local_path = saved


def test_list_allowed_roots_always_includes_the_workspace_root() -> None:
    body = client.get('/api/settings/allowed-roots').json()
    sources = {entry['source'] for entry in body}
    paths = {entry['path'] for entry in body}
    assert 'workspace' in sources
    assert str(settings.workspace_root.resolve()) in paths


def test_registering_outside_project_fails_until_root_is_added(outside_folder: Path, strict_roots: None) -> None:
    denied = client.post('/api/projects', json={'name': 'outside-before', 'path': str(outside_folder)})
    assert denied.status_code == 400
    assert 'allowed roots' in denied.json()['detail']

    add = client.post('/api/settings/allowed-roots', json={'path': str(outside_folder)})
    assert add.status_code == 200, add.text

    allowed = client.post('/api/projects', json={'name': 'outside-after', 'path': str(outside_folder)})
    assert allowed.status_code == 200, allowed.text


def test_added_root_appears_in_the_list_with_dynamic_source(outside_folder: Path) -> None:
    client.post('/api/settings/allowed-roots', json={'path': str(outside_folder)})
    body = client.get('/api/settings/allowed-roots').json()
    match = next((entry for entry in body if entry['path'] == str(outside_folder.resolve())), None)
    assert match is not None
    assert match['source'] == 'dynamic'
    assert match['id'] is not None


def test_add_allowed_root_rejects_a_path_that_does_not_exist() -> None:
    response = client.post('/api/settings/allowed-roots', json={'path': str(settings.workspace_root / 'nope-xyz')})
    assert response.status_code == 400


def test_add_allowed_root_rejects_sensitive_paths() -> None:
    sensitive = settings.workspace_root / '.ssh'
    sensitive.mkdir(exist_ok=True)
    response = client.post('/api/settings/allowed-roots', json={'path': str(sensitive)})
    assert response.status_code == 400
    assert 'blocked' in response.json()['detail'].lower()


def test_adding_the_same_root_twice_is_a_harmless_no_op(outside_folder: Path) -> None:
    first = client.post('/api/settings/allowed-roots', json={'path': str(outside_folder)})
    second = client.post('/api/settings/allowed-roots', json={'path': str(outside_folder)})
    assert first.status_code == 200
    assert second.status_code == 200
    body = client.get('/api/settings/allowed-roots').json()
    matches = [entry for entry in body if entry['path'] == str(outside_folder.resolve())]
    assert len(matches) == 1


def test_removing_a_root_revokes_access(outside_folder: Path, strict_roots: None) -> None:
    client.post('/api/settings/allowed-roots', json={'path': str(outside_folder)})
    listed = client.get('/api/settings/allowed-roots').json()
    match = next(entry for entry in listed if entry['path'] == str(outside_folder.resolve()))

    # A never-before-registered subfolder under the allowed root, so this
    # test only depends on the root itself being revoked - not on deleting
    # a project row to work around projects.path's UNIQUE constraint.
    nested = outside_folder / 'nested'
    nested.mkdir(exist_ok=True)
    allowed = client.post('/api/projects', json={'name': 'before-removal', 'path': str(nested)})
    assert allowed.status_code == 200, allowed.text

    removed = client.delete(f"/api/settings/allowed-roots/{match['id']}")
    assert removed.status_code == 200

    denied = client.post('/api/projects', json={'name': 'after-removal', 'path': str(outside_folder)})
    assert denied.status_code == 400


def test_sync_allowed_roots_rebuilds_from_db_without_a_restart(outside_folder: Path, strict_roots: None) -> None:
    """Simulates what happens on a fresh process start: `settings.allowed_roots`
    only has to be rebuilt from the DB via sync_allowed_roots() - no server
    restart, no re-reading .env - for a previously-added root to work again."""
    services.add_allowed_root(str(outside_folder))
    settings.allowed_roots = ''  # pretend this is a brand-new process with no in-memory state yet
    services.sync_allowed_roots()
    allowed = client.post('/api/projects', json={'name': 'after-sync', 'path': str(outside_folder)})
    assert allowed.status_code == 200, allowed.text
