"""Read-only Git tools: status / log / branches / diff / blame.

These run git as a subprocess with cwd = the registered project path. The
project folder may or may not be a git repository; non-repo folders must
surface a clear message rather than crash. Path arguments to diff/blame are
validated via the policy layer (safe_join) so traversal is rejected.
"""
from __future__ import annotations

import itertools
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from services.api.app import services
from services.api.app.config import settings
from services.api.app.git_tools import (
    git_blame,
    git_branches,
    git_diff,
    git_log,
    git_status,
)
from services.api.app.main import app

client = TestClient(app)

# Per-process counter so each fixture repo path is unique (the projects table
# has a UNIQUE constraint on path and tests share one session DB).
_repo_counter = itertools.count()


def _git_available() -> bool:
    return shutil.which('git') is not None


pytestmark = pytest.mark.skipif(not _git_available(), reason='git not installed')


def _make_repo(name: str) -> Path:
    """Create a real throwaway git repo with one committed file + one dirty file."""
    import itertools
    import os
    counter = next(_repo_counter)
    path = settings.workspace_root / f'git-{counter}-{name}'
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)
    path.mkdir(parents=True, exist_ok=True)
    env = {
        'GIT_AUTHOR_NAME': 'Tester', 'GIT_AUTHOR_EMAIL': 't@example.com',
        'GIT_COMMITTER_NAME': 'Tester', 'GIT_COMMITTER_EMAIL': 't@example.com',
    }
    full_env = {**os.environ, **env}

    def g(*args: str) -> None:
        subprocess.run(['git', *args], cwd=path, check=True, capture_output=True, env=full_env)

    g('init')
    g('config', 'user.email', 't@example.com')
    g('config', 'user.name', 'Tester')
    (path / 'committed.txt').write_text('MARKER_COMMITTED_LINE_ONE\n', encoding='utf-8')
    g('add', '.')
    g('commit', '-m', 'first commit')
    # now make the working tree dirty
    (path / 'committed.txt').write_text('MARKER_COMMITTED_LINE_ONE\nNEW_UNCOMMITTED_LINE\n', encoding='utf-8')
    (path / 'untracked.txt').write_text('fresh\n', encoding='utf-8')
    return path


def _make_git_project(name: str = 'gitdemo') -> dict:
    repo_path = _make_repo(name)
    return services.create_project(name, str(repo_path))


# ---------- helpers ----------

def test_git_status_reports_dirty_and_untracked() -> None:
    repo = _make_repo('status')
    status = git_status(repo)
    assert status['is_repo'] is True
    assert any('committed.txt' in e for e in status['unstaged'] + status['staged'])
    assert any('untracked.txt' in e for e in status['untracked'])


def test_git_log_returns_commits_with_hash_and_message() -> None:
    repo = _make_repo('log')
    log = git_log(repo, limit=10)
    assert log, 'expected at least one commit'
    entry = log[0]
    assert 'hash' in entry and entry['hash']
    assert 'first commit' in entry['message']


def test_git_branches_reports_current() -> None:
    repo = _make_repo('branches')
    branches = git_branches(repo)
    assert branches['current'], 'expected a current branch'
    assert any(br == branches['current'] for br in branches['local'])


def test_git_diff_includes_uncommitted_change() -> None:
    repo = _make_repo('diff')
    diff = git_diff(repo)
    assert 'NEW_UNCOMMITTED_LINE' in diff


def test_git_blame_returns_lines() -> None:
    repo = _make_repo('blame')
    blame = git_blame(repo, 'committed.txt')
    assert blame, 'expected at least one blame line'
    assert any('MARKER_COMMITTED_LINE_ONE' in line.get('content', '') for line in blame)


def test_non_git_folder_raises_runtime_error() -> None:
    plain = settings.workspace_root / 'not-a-repo'
    plain.mkdir(parents=True, exist_ok=True)
    (plain / 'f.txt').write_text('x', encoding='utf-8')
    with pytest.raises(RuntimeError):
        git_status(plain)


# ---------- endpoints ----------

def test_endpoint_git_status_returns_structured_dict() -> None:
    project = _make_git_project('endpoint')
    response = client.get(f"/api/projects/{project['id']}/git/status")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body['is_repo'] is True
    assert 'unstaged' in body and 'untracked' in body


def test_endpoint_git_diff_path_traversal_is_rejected() -> None:
    project = _make_git_project('traversal')
    response = client.get(
        f"/api/projects/{project['id']}/git/diff",
        params={'path': '../../../../etc/passwd'},
    )
    # safe_join rejects traversal before git ever sees the path.
    assert response.status_code == 400, response.text


def test_endpoint_git_for_non_repo_project_returns_400() -> None:
    plain = settings.workspace_root / f'norepo-{next(_repo_counter)}'
    plain.mkdir(parents=True, exist_ok=True)
    (plain / 'f.txt').write_text('x', encoding='utf-8')
    project = services.create_project('norepo', str(plain))
    response = client.get(f"/api/projects/{project['id']}/git/status")
    assert response.status_code == 400, response.text
    assert 'not a git repository' in response.json()['detail'].lower()
