from __future__ import annotations

import os
from pathlib import Path

from .config import settings


BLOCKED_PARTS = {
    '.ssh', '.gnupg', 'AppData', 'Windows', 'System32', 'Credentials',
    'Google/Chrome/User Data', 'Microsoft/Edge/User Data'
}
BLOCKED_FILENAMES = {'.env', '.npmrc', '.pypirc', 'id_rsa', 'id_ed25519', 'credentials.json'}


def resolve_allowed_path(raw_path: str, *, must_exist: bool = True) -> Path:
    path = Path(raw_path).expanduser().resolve()
    if must_exist and not path.exists():
        raise ValueError(f'Path does not exist: {path}')

    normalized = str(path).replace('\\', '/')
    if any(part.lower() in normalized.lower() for part in BLOCKED_PARTS):
        raise ValueError('This sensitive system or credential path is blocked by policy.')
    if path.name.lower() in BLOCKED_FILENAMES or (path.name.lower().startswith('.env') and path.name.lower() != '.env.example'):
        raise ValueError('Secret-bearing files are blocked by policy.')

    if settings.allow_any_local_path:
        return path

    extra_roots = [Path(item.strip()).expanduser().resolve() for item in settings.allowed_roots.split(os.pathsep) if item.strip()]
    roots = [settings.workspace_root.resolve(), *extra_roots]
    if not any(path == root or root in path.parents for root in roots):
        raise ValueError(
            f'Path is outside allowed roots. Place the project under {settings.workspace_root} '
            'or enable INMYAI_ALLOW_ANY_LOCAL_PATH explicitly.'
        )
    return path


def safe_join(project_root: Path, relative_path: str, *, must_exist: bool = True) -> Path:
    candidate = (project_root / relative_path).resolve()
    if project_root != candidate and project_root not in candidate.parents:
        raise ValueError('Path traversal is not allowed.')
    return resolve_allowed_path(str(candidate), must_exist=must_exist)


def resolve_browsable_path(raw_path: str) -> Path:
    """Resolve a directory for read-only browsing (the Explorer tab's mind-map).

    Deliberately skips the allowed-roots check that `resolve_allowed_path`
    enforces: on a single-user local machine, looking at folder *names* to
    find a project is not a meaningful security boundary, and requiring an
    `.env` whitelist edit just to look around defeats the point of a
    discovery UI. The sensitive-path blocklist (BLOCKED_PARTS) still applies
    unconditionally, since that protects against a different concern -
    accidentally walking into credential/system directories - not
    multi-tenant access control. Actually registering a project for indexing
    still goes through `resolve_allowed_path` in `create_project`, so opening
    a project's *contents* is unaffected by this relaxation.
    """
    path = Path(raw_path).expanduser().resolve()
    if not path.exists():
        raise ValueError(f'Path does not exist: {path}')
    if not path.is_dir():
        raise ValueError(f'Not a directory: {path}')
    normalized = str(path).replace('\\', '/')
    if any(part.lower() in normalized.lower() for part in BLOCKED_PARTS):
        raise ValueError('This sensitive system or credential path is blocked by policy.')
    return path


PROJECT_MARKERS = {'.git', 'package.json', 'pyproject.toml', 'requirements.txt', 'go.mod', 'Cargo.toml'}


def looks_like_project(path: Path) -> bool:
    """Heuristic used only to visually flag a folder in the Explorer mind-map
    (a differently-styled node) - it never blocks navigation. Cheap by
    design: a handful of `exists()` calls, not a directory walk."""
    try:
        return any((path / marker).exists() for marker in PROJECT_MARKERS)
    except OSError:
        return False
