"""Shared test harness for the InMyAI API test suite.

A single session-scoped, autouse fixture redirects settings (and therefore the
SQLite database and the workspace root) to an isolated repo-local directory
(`.test-runtime/`), then seeds the shared demo project. This guarantees every
test file — even when run in isolation — operates on throwaway state instead of
mutating the production `./workspace` and `./data/runtime` under the repo root.

We deliberately avoid the OS temp dir: on Windows it lives under AppData,
which the InMyAI path policy blocks (correctly, for production safety). The
test harness opts into `allow_any_local_path` for the session so the policy
layer does not interfere with temp-project creation during tests.

Per-test DB isolation is out of scope: all tests in a session share one temp
DB. That is enough to keep production state safe and make test order
irrelevant for the workspace/data_dir configuration.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

# Ensure the repo root is importable when pytest is invoked from anywhere.
_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from services.api.app.config import settings  # noqa: E402
from services.api.app.database import migrate  # noqa: E402

_TEMP_ROOT = _ROOT / '.test-runtime'


@pytest.fixture(scope='session', autouse=True)
def _isolate_settings() -> None:
    """Point settings at a per-session temp root and seed the demo project."""
    if _TEMP_ROOT.exists():
        shutil.rmtree(_TEMP_ROOT, ignore_errors=True)
    _TEMP_ROOT.mkdir(parents=True, exist_ok=True)

    settings.data_dir = _TEMP_ROOT / 'data'
    settings.workspace_root = _TEMP_ROOT / 'workspace'
    # The temp workspace is not under the production allowed-roots; tests are
    # single-user and throwaway, so bypass the root allowlist for the session.
    settings.allow_any_local_path = True
    settings.ensure_dirs()

    project = settings.workspace_root / 'demo'
    project.mkdir(parents=True, exist_ok=True)
    (project / 'README.md').write_text('# Demo\n\nThe active database is SQLite.\n', encoding='utf-8')
    (project / 'main.ts').write_text(
        "import { login } from './auth'\nexport function run(){ return login() }\n",
        encoding='utf-8',
    )
    (project / 'auth.ts').write_text('export function login(){ return true }\n', encoding='utf-8')
    image = Image.new('RGB', (500, 160), 'white')
    ImageDraw.Draw(image).text((20, 50), 'INVOICE 2026 TEST', fill='black')
    image.save(project / 'invoice.png')

    migrate()
