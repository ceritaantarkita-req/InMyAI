"""Read-only Git inspection helpers.

Run git as a subprocess with cwd = a registered project path. Only read-only
commands are issued (status/log/diff/branch/blame) — never add/commit/push/
reset — so a project's repository is never mutated through InMyAI.

Security:
- subprocess.run uses a list of args (no shell=True), so there is no shell
  injection surface.
- the cwd is the project path, already validated at registration.
- file-path arguments to diff/blame are canonicalized by the caller via
  services.safe_join before reaching here; this module trusts that contract.

A folder that is not a git repository, or a machine without git installed,
raises RuntimeError with a clear message — the API layer turns that into 400.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

GIT_TIMEOUT_SECONDS = 15


def _git_binary() -> str:
    binary = shutil.which('git')
    if binary is None:
        raise RuntimeError('git is not installed or not on PATH.')
    return binary


def _run_git(args: list[str], cwd: Path, timeout: int = GIT_TIMEOUT_SECONDS) -> str:
    """Run a git command in cwd and return stdout. Raise RuntimeError on failure."""
    try:
        result = subprocess.run(
            [_git_binary(), *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f'git {args[0]} timed out after {timeout}s.') from exc
    if result.returncode != 0:
        stderr = result.stderr.strip()
        if 'not a git repository' in stderr or 'not a git dir' in stderr.lower():
            raise RuntimeError(f'{cwd} is not a git repository.')
        raise RuntimeError(stderr or f'git {args[0]} failed (exit {result.returncode}).')
    return result.stdout


def _ensure_repo(cwd: Path) -> None:
    """Confirm cwd is itself a git work tree.

    git walks up to find a parent .git, which would make a plain subfolder
    inside a repo report as 'inside a work tree'. We require the repo root to
    actually be cwd (resolved), so a registered non-repo folder is rejected even
    if it happens to live below another repository.
    """
    try:
        toplevel = _run_git(['rev-parse', '--show-toplevel'], cwd).strip()
    except RuntimeError:
        raise
    except Exception as exc:  # pragma: no cover - defensive
        raise RuntimeError(f'{cwd} is not a git repository.') from exc
    try:
        same = Path(toplevel).resolve() == Path(cwd).resolve()
    except (OSError, ValueError):
        same = False
    if not same:
        raise RuntimeError(f'{cwd} is not a git repository (no .git at this folder).')


def git_status(cwd: Path) -> dict:
    """Return staged/unstaged/untracked entries plus current branch."""
    _ensure_repo(cwd)
    raw = _run_git(['status', '--porcelain=v1', '-b'], cwd)
    staged: list[str] = []
    unstaged: list[str] = []
    untracked: list[str] = []
    branch = ''
    for line in raw.splitlines():
        if line.startswith('## '):
            branch = line[3:].split('...')[0].strip()
            continue
        if len(line) < 3:
            continue
        xy, path = line[:2], line[3:]
        path = path.strip()
        if '??' in xy:
            untracked.append(path)
        elif xy[1] != ' ' and xy[1] != '?':
            unstaged.append(path)
        if xy[0] != ' ' and xy[0] != '?' and xy[0] != '!':
            staged.append(path)
    return {
        'is_repo': True,
        'branch': branch,
        'staged': staged,
        'unstaged': unstaged,
        'untracked': untracked,
    }


def git_log(cwd: Path, limit: int = 50) -> list[dict]:
    """Return recent commits as dicts {hash, author, date, message}."""
    _ensure_repo(cwd)
    sep = '\x1f'  # ASCII unit separator — never appears in commit fields
    record_sep = '\x1e'  # ASCII record separator
    fmt = sep.join(['%H', '%an', '%ad', '%s'])
    raw = _run_git(
        ['log', f'-n{limit}', f'--pretty=format:{fmt}{record_sep}', '--date=short'],
        cwd,
    )
    entries: list[dict] = []
    for chunk in raw.split(record_sep):
        chunk = chunk.strip('\n')
        if not chunk:
            continue
        parts = chunk.split(sep)
        if len(parts) < 4:
            continue
        entries.append({
            'hash': parts[0], 'author': parts[1], 'date': parts[2], 'message': parts[3],
        })
    return entries


def git_branches(cwd: Path) -> dict:
    """Return {current, local, remote} branch names."""
    _ensure_repo(cwd)
    current = _run_git(['rev-parse', '--abbrev-ref', 'HEAD'], cwd).strip()
    raw = _run_git(['branch', '--list', '--all', '--format=%(refname:short)'], cwd)
    local: list[str] = []
    remote: list[str] = []
    for line in raw.splitlines():
        name = line.strip()
        if not name:
            continue
        if name.startswith('remotes/'):
            remote.append(name[len('remotes/'):])
        elif '/' not in name or name.startswith('HEAD'):
            local.append(name)
    return {'current': current, 'local': sorted(set(local)), 'remote': sorted(set(remote))}


def git_diff(cwd: Path, path: str | None = None) -> str:
    """Return the working-tree diff. If path given, restrict to that file."""
    _ensure_repo(cwd)
    args = ['diff', '--no-color']
    if path:
        args.extend(['--', path])
    # diff against HEAD so staged+unstaged changes both surface; fall back to unstaged.
    try:
        return _run_git(['diff', '--no-color', 'HEAD'] + (['--', path] if path else []), cwd)
    except RuntimeError:
        return _run_git(args, cwd)


def git_blame(cwd: Path, path: str) -> list[dict]:
    """Return per-line blame entries: {commit, author, content}.

    Uses the default (non-porcelain) blame format: lines like
    `<short-hash> (<author> <date> <time> <tz> <lineno>) <content>`.
    """
    _ensure_repo(cwd)
    if not path:
        raise RuntimeError('git blame requires a file path.')
    raw = _run_git(['blame', '-w', '--abbrev-commit', '--', path], cwd)
    lines: list[dict] = []
    for ln in raw.splitlines():
        ln = ln.rstrip('\n')
        if not ln:
            continue
        # Boundary commits are prefixed with '^'; strip it so the hash parses.
        if ln.startswith('^'):
            ln = ln[1:]
        # Split off the commit hash, then the parenthesized header, keep the rest as content.
        first_space = ln.find(' ')
        commit = ln[:first_space] if first_space > 0 else ''
        rest = ln[first_space + 1:] if first_space > 0 else ln
        author = ''
        content = rest
        if rest.startswith('('):
            close = rest.find(')')
            if close > 0:
                header = rest[1:close]
                content = rest[close + 1:].lstrip()
                author = header.split()[0] if header.split() else ''
        lines.append({'commit': commit, 'author': author, 'content': content})
    return lines
