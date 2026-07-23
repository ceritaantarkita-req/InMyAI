"""Phase 2 Task 2: a guardrail that flags accidentally-too-wide folders (system
dirs, drive roots, user profile) before registration, WITHOUT blocking the
user's real cross-project workflow (a parent folder holding many sibling
projects is NOT flagged as dangerous).

The >20 subfolder count is reported as a non-blocking large_folder notice,
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


def test_path_inside_documents_is_not_flagged_dangerous() -> None:
    """A folder INSIDE Documents is a legitimate place to keep a specific
    project, so it must NOT be flagged dangerous. Only the Documents folder
    itself is an accident target. This pins the intended behavior the test
    suite previously left ambiguous (I2 from code review)."""
    docs = Path.home() / 'Documents'
    if not docs.exists():
        import pytest
        pytest.skip('No Documents folder on this machine')
    sub = docs / 'inmyai_test_subproj'
    sub.mkdir(parents=True, exist_ok=True)
    try:
        result = services.classify_folder_scope(str(sub))
        assert result['is_dangerous'] is False, result
        assert result['dangerous_match'] is None
    finally:
        sub.rmdir()  # only succeeds if empty, which it is


def test_dotdot_traversal_normalizes_before_classification() -> None:
    """A path using '..' must be resolved to its real target before danger
    detection, so `~/normal_proj/../..` cannot smuggle past the home-dir
    check (M2 from code review)."""
    root = settings.workspace_root / 'scope_traversal'
    root.mkdir(parents=True, exist_ok=True)
    payload = str(root / 'x' / '..' / '.')
    result = services.classify_folder_scope(payload)
    assert result['is_dangerous'] is False
    # And a traversal that resolves back to home must still be flagged.
    home_via_parent = str(Path.home() / 'x' / '..')
    result_home = services.classify_folder_scope(home_via_parent)
    assert result_home['is_dangerous'] is True
