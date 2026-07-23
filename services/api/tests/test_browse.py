"""Tests for GET /api/browse - the read-only directory listing that powers
the Explorer tab's mind-map (see docs/decisions/ for the design rationale).

Key behavior under test: browsing is NOT subject to INMYAI_ALLOWED_ROOTS
(unlike registering a project), the sensitive-path blocklist still applies,
and folders that look like a real project (.git/package.json/etc.) are
flagged via `is_project` for the UI to style differently.

Deliberately does NOT use pytest's `tmp_path` fixture: on Windows, tmp_path
lives under `...\\AppData\\Local\\Temp\\...`, and `AppData` is itself one of
the sensitive-path substrings this module's own blocklist rejects - using it
would make every "should succeed" test here fail specifically on Windows
(the platform this app actually ships on) while passing in a Linux sandbox.
Scratch folders are created under settings.workspace_root instead, matching
every other test file's convention (see conftest.py's session-isolated
workspace_root), which is guaranteed not to collide with the blocklist.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from services.api.app.config import settings
from services.api.app.main import app

client = TestClient(app)


@pytest.fixture()
def scratch_dir() -> Path:
    root = settings.workspace_root / 'browse-scratch'
    (root / 'plain-folder').mkdir(parents=True, exist_ok=True)
    (root / 'a-project').mkdir(exist_ok=True)
    (root / 'a-project' / 'package.json').write_text('{}', encoding='utf-8')
    (root / 'notes.txt').write_text('hello', encoding='utf-8')
    (root / '.env').write_text('SECRET=1', encoding='utf-8')
    return root


def test_browse_lists_entries_with_names_and_types(scratch_dir: Path) -> None:
    response = client.get('/api/browse', params={'path': str(scratch_dir)})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body['path'] == str(scratch_dir.resolve())
    names = {entry['name']: entry for entry in body['entries']}
    assert 'plain-folder' in names
    assert names['plain-folder']['is_dir'] is True
    assert names['plain-folder']['is_project'] is False
    assert 'notes.txt' in names
    assert names['notes.txt']['is_dir'] is False


def test_browse_flags_project_looking_folders(scratch_dir: Path) -> None:
    body = client.get('/api/browse', params={'path': str(scratch_dir)}).json()
    names = {entry['name']: entry for entry in body['entries']}
    assert names['a-project']['is_project'] is True


def test_browse_hides_dotenv_and_credential_filenames(scratch_dir: Path) -> None:
    body = client.get('/api/browse', params={'path': str(scratch_dir)}).json()
    names = {entry['name'] for entry in body['entries']}
    assert '.env' not in names


def test_browse_works_without_allowlisting(scratch_dir: Path) -> None:
    """The whole point of /api/browse: it must succeed even for a target
    outside allowed_roots and even when allow_any_local_path is off - unlike
    project registration, which must still be rejected under the same
    restricted settings (the contrast this test actually pins down)."""
    outside = settings.workspace_root.parent / 'outside-workspace-root-scratch'
    outside.mkdir(exist_ok=True)
    saved_allow_any = settings.allow_any_local_path
    saved_roots = settings.allowed_roots
    settings.allow_any_local_path = False
    settings.allowed_roots = ''
    try:
        response = client.get('/api/browse', params={'path': str(outside)})
        assert response.status_code == 200, response.text

        register = client.post('/api/projects', json={'name': 'outside', 'path': str(outside)})
        assert register.status_code == 400
        assert 'allowed roots' in register.json()['detail']
    finally:
        settings.allow_any_local_path = saved_allow_any
        settings.allowed_roots = saved_roots


def test_browse_rejects_missing_path() -> None:
    response = client.get('/api/browse', params={'path': str(settings.workspace_root / 'does-not-exist-xyz')})
    assert response.status_code == 400


def test_browse_rejects_a_file_path(scratch_dir: Path) -> None:
    response = client.get('/api/browse', params={'path': str(scratch_dir / 'notes.txt')})
    assert response.status_code == 400


def test_browse_rejects_sensitive_path_even_without_allowlist_restriction() -> None:
    sensitive = settings.workspace_root / '.ssh'
    sensitive.mkdir(exist_ok=True)
    response = client.get('/api/browse', params={'path': str(sensitive)})
    assert response.status_code == 400
    assert 'blocked' in response.json()['detail'].lower()


def test_browse_parent_is_reported(scratch_dir: Path) -> None:
    body = client.get('/api/browse', params={'path': str(scratch_dir / 'plain-folder')}).json()
    assert body['parent'] == str(scratch_dir.resolve())
