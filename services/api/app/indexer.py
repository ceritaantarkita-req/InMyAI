from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Iterable

from pypdf import PdfReader

from .config import settings
from .database import transaction, utc_now

TEXT_EXTENSIONS = {
    '.md', '.txt', '.json', '.jsonl', '.yaml', '.yml', '.toml', '.ini', '.env.example',
    '.py', '.js', '.jsx', '.ts', '.tsx', '.css', '.scss', '.html', '.sql', '.sh', '.ps1',
    '.go', '.rs', '.java', '.c', '.h', '.cpp', '.hpp', '.cs', '.php', '.rb', '.swift', '.kt'
}
SKIP_DIRS = {
    '.git', '.next', 'node_modules', 'dist', 'build', 'coverage', '.venv', 'venv',
    '__pycache__', '.cache', 'models', 'downloads', 'artifacts', 'generated'
}


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_text(path: Path) -> str:
    if path.suffix.lower() == '.pdf':
        reader = PdfReader(str(path))
        return '\n\n'.join(page.extract_text() or '' for page in reader.pages)
    data = path.read_bytes()
    if b'\x00' in data[:4096]:
        return ''
    for encoding in ('utf-8', 'utf-8-sig', 'latin-1'):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return ''


def iter_indexable_files(root: Path) -> Iterable[Path]:
    count = 0
    for path in root.rglob('*'):
        if count >= settings.max_index_files:
            break
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        suffix = path.suffix.lower()
        if suffix not in TEXT_EXTENSIONS and suffix != '.pdf':
            continue
        if path.stat().st_size > settings.max_file_mb * 1024 * 1024:
            continue
        count += 1
        yield path


def _extract_relations(project_id: int, relative: str, content: str) -> list[tuple]:
    rows: list[tuple] = []
    source = relative
    import_patterns = [
        r"(?:from\s+['\"]([^'\"]+)['\"]|import\s+.+?\s+from\s+['\"]([^'\"]+)['\"])",
        r"from\s+([\w\.]+)\s+import",
        r"import\s+([\w\.]+)"
    ]
    for pattern in import_patterns:
        for match in re.finditer(pattern, content):
            target = next((g for g in match.groups() if g), '')
            if target:
                rows.append((project_id, source, 'imports', target, match.group(0)[:300], 'EXTRACTED'))
    for match in re.finditer(r'^(?:export\s+)?(?:async\s+)?(?:function|class|interface|type)\s+([A-Za-z_][A-Za-z0-9_]*)', content, re.M):
        rows.append((project_id, source, 'defines', match.group(1), match.group(0), 'EXTRACTED'))
    return rows


def index_project(project_id: int, root: Path) -> dict:
    indexed = 0
    unchanged = 0
    errors: list[str] = []
    seen: set[str] = set()
    now = utc_now()

    with transaction() as conn:
        for path in iter_indexable_files(root):
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
                content = _read_text(path)
                if not content.strip():
                    continue
                if existing:
                    file_id = existing['id']
                    conn.execute(
                        '''UPDATE files SET absolute_path=?, extension=?, size_bytes=?, modified_ns=?,
                           sha256=?, content=?, indexed_at=? WHERE id=?''',
                        (str(path), path.suffix.lower(), stat.st_size, stat.st_mtime_ns,
                         digest, content, now, file_id)
                    )
                    conn.execute('DELETE FROM files_fts WHERE file_id=?', (file_id,))
                else:
                    cur = conn.execute(
                        '''INSERT INTO files(project_id, relative_path, absolute_path, extension, size_bytes,
                           modified_ns, sha256, content, indexed_at) VALUES(?,?,?,?,?,?,?,?,?)''',
                        (project_id, relative, str(path), path.suffix.lower(), stat.st_size,
                         stat.st_mtime_ns, digest, content, now)
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
            'INSERT INTO audit_log(project_id,action,detail,created_at) VALUES(?,?,?,?)',
            (project_id, 'project.indexed', json.dumps({'indexed': indexed, 'unchanged': unchanged, 'errors': errors}), now)
        )

    return {'indexed': indexed, 'unchanged': unchanged, 'removed': len(removed), 'errors': errors}
