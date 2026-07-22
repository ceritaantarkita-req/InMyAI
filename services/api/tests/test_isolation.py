"""Test isolation contract.

These tests assert that the test harness points settings (and therefore the
SQLite DB and the workspace root) at an isolated temp location, never at the
production defaults under the repo working tree. They must pass when run in
isolation (e.g. `pytest services/api/tests/test_isolation.py`) — that is the
whole point: a single test file must not depend on test_core having run first.
"""
from __future__ import annotations

from pathlib import Path

from services.api.app.config import settings


def test_workspace_root_is_not_the_production_default() -> None:
    # The production default is './workspace' relative to the repo root.
    # The harness must redirect this to a temp dir.
    resolved = settings.workspace_root.resolve()
    production = Path('./workspace').resolve()
    assert resolved != production, (
        f'workspace_root still points at the production default {production}; '
        'tests would write into the real workspace.'
    )


def test_database_path_is_under_temp_root() -> None:
    # The DB file must live under the same temp root as workspace_root, not
    # under ./data/runtime in the repo.
    db = settings.database_path.resolve()
    repo_data = Path('./data/runtime').resolve()
    assert not db.is_relative_to(repo_data), (
        f'database_path {db} is under the production data dir {repo_data}; '
        'tests would mutate the real SQLite DB.'
    )


def test_settings_point_at_test_runtime_dir() -> None:
    # Both roots must live under .test-runtime (the harness's temp root).
    resolved = settings.workspace_root.resolve()
    assert '.test-runtime' in resolved.parts, (
        f'workspace_root {resolved} is not under the .test-runtime harness dir'
    )


def test_workspace_root_actually_exists() -> None:
    # ensure_dirs() must have created it during setup.
    assert settings.workspace_root.exists()
    assert settings.workspace_root.is_dir()


def test_demo_project_is_seeded() -> None:
    # The shared demo fixture must exist so create_demo_project() works.
    demo = settings.workspace_root / 'demo'
    assert demo.exists(), 'demo project dir should be seeded by the harness'
    assert (demo / 'README.md').exists()
