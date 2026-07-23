from __future__ import annotations

import difflib
import hashlib
import json
import os
import random
import re
import shutil
import sqlite3
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

import networkx as nx
import psutil
from PIL import Image, ImageDraw, ImageFont
from pypdf import PdfReader

from .config import settings
from .database import connect, row_to_dict, transaction, utc_now
from .security import BLOCKED_PARTS, resolve_allowed_path, safe_join

# The env-configured allowed roots, captured once at process start-up,
# before anything below ever mutates `settings.allowed_roots` in memory.
# Every add/remove of a dynamic (UI-managed) root rebuilds
# `settings.allowed_roots` from this fixed baseline plus the current
# `allowed_roots` DB rows, rather than editing the string incrementally -
# that keeps repeated add/remove cycles from drifting or duplicating
# entries, and keeps `.env`'s own setting authoritative and untouched.
_ENV_ALLOWED_ROOTS = settings.allowed_roots


def sync_allowed_roots() -> None:
    """Rebuild `settings.allowed_roots` from the env baseline plus whatever
    is currently in the `allowed_roots` table. `resolve_allowed_path`
    (security.py) reads `settings.allowed_roots` fresh on every call, so
    this takes effect immediately for the running process - no restart
    needed. Called once at API startup (to restore roots added in a
    previous run) and again after every add/remove."""
    with connect() as conn:
        rows = conn.execute('SELECT path FROM allowed_roots').fetchall()
    dynamic_paths = [row['path'] for row in rows]
    settings.allowed_roots = os.pathsep.join(p for p in [_ENV_ALLOWED_ROOTS, *dynamic_paths] if p)


def _is_strictly_within(inner: Path, outer: Path) -> bool:
    """True if `inner` is `outer` itself or deeper - i.e. `outer` already
    covers `inner`, making a separate allow-list entry for `inner`
    redundant. Never true for two equal paths (that's a duplicate, not
    coverage, and both should stay visible so either can be removed)."""
    if inner == outer:
        return False
    try:
        inner.relative_to(outer)
        return True
    except ValueError:
        return False


def list_allowed_roots() -> list[dict]:
    """Every folder InMyAI will currently accept for `POST /api/projects`,
    from all three sources: the always-allowed workspace root, whatever
    `INMYAI_ALLOWED_ROOTS` set in `.env` (read-only from the UI - it only
    changes by editing `.env` and restarting), and whatever has been added
    at runtime through this settings UI (deletable).

    Entries already covered by a *broader* root elsewhere in the list are
    hidden - e.g. if both `.../demo` and `.../demo/InMyAI_FullStack/workspace`
    are allowed, only `.../demo` is shown, since it already grants access to
    everything beneath it. Nothing is deleted from the database by this -
    the narrower entry simply reappears if the broader one is later
    removed."""
    workspace = [{'id': None, 'source': 'workspace', 'path': str(settings.workspace_root.resolve()), 'created_at': None}]
    env_roots = [
        {'id': None, 'source': 'env', 'path': item.strip(), 'created_at': None}
        for item in _ENV_ALLOWED_ROOTS.split(os.pathsep) if item.strip()
    ]
    with connect() as conn:
        rows = conn.execute('SELECT id, path, created_at FROM allowed_roots ORDER BY created_at').fetchall()
    dynamic_roots = [{**dict(row), 'source': 'dynamic'} for row in rows]
    all_roots = workspace + env_roots + dynamic_roots
    parsed = [Path(r['path']) for r in all_roots]
    return [
        root for i, root in enumerate(all_roots)
        if not any(_is_strictly_within(parsed[i], parsed[j]) for j in range(len(all_roots)) if j != i)
    ]


def add_allowed_root(raw_path: str) -> dict:
    path = Path(raw_path).expanduser().resolve()
    if not path.exists() or not path.is_dir():
        raise ValueError(f'Not a directory: {path}')
    normalized = str(path).replace('\\', '/')
    if any(part.lower() in normalized.lower() for part in BLOCKED_PARTS):
        raise ValueError('This sensitive system or credential path is blocked by policy.')
    now = utc_now()
    with transaction() as conn:
        try:
            conn.execute('INSERT INTO allowed_roots(path, created_at) VALUES(?, ?)', (str(path), now))
        except sqlite3.IntegrityError:
            pass  # already allowed - adding it again is a harmless no-op, not an error
    sync_allowed_roots()
    return {'path': str(path)}


def remove_allowed_root(root_id: int) -> None:
    with transaction() as conn:
        conn.execute('DELETE FROM allowed_roots WHERE id = ?', (root_id,))
    sync_allowed_roots()


def list_projects() -> list[dict]:
    with connect() as conn:
        return [dict(row) for row in conn.execute('SELECT * FROM projects ORDER BY created_at DESC')]


def get_project(project_id: int) -> dict:
    with connect() as conn:
        row = conn.execute('SELECT * FROM projects WHERE id=?', (project_id,)).fetchone()
    if not row:
        raise KeyError('Project not found')
    return dict(row)


_DANGEROUS_FOLDER_NAMES = {'documents', 'desktop', 'downloads', 'home', 'users', 'windows'}
_DANGEROUS_FOLDER_PREFIXES = ('program files', 'program files (x86)')


def classify_folder_scope(raw_path: str) -> dict:
    """Classify a folder before registration to guard against accidental
    'register everything' mistakes.

    Returns:
        is_dangerous: True only for system/profile/drive-root targets.
        dangerous_match: short label of what matched, or None.
        direct_subdirs: count of immediate subdirectories.
        large_folder: True when direct_subdirs exceeds the non-blocking
            notice threshold (the user may still proceed).
    """
    try:
        path = Path(raw_path).expanduser().resolve()
    except (OSError, ValueError):
        return {'is_dangerous': False, 'dangerous_match': None, 'direct_subdirs': 0, 'large_folder': False}

    is_dangerous = False
    dangerous_match: str | None = None

    # `path == path.parent` is true for both POSIX filesystem root (/) and
    # Windows drive roots (C:\) — they have no parent. The drive label just
    # makes the user-facing message more specific.
    if path == path.parent:
        is_dangerous = True
        dangerous_match = 'drive root' if path.drive else 'filesystem root'
    else:
        final = path.name.lower()
        if final in _DANGEROUS_FOLDER_NAMES:
            is_dangerous, dangerous_match = True, path.name
        elif any(final.startswith(p) for p in _DANGEROUS_FOLDER_PREFIXES):
            is_dangerous, dangerous_match = True, path.name
        elif path == Path.home():
            is_dangerous, dangerous_match = True, 'user profile root'

    direct_subdirs = 0
    try:
        if path.is_dir():
            direct_subdirs = sum(1 for child in path.iterdir() if child.is_dir())
    except (OSError, PermissionError):
        direct_subdirs = 0

    LARGE_FOLDER_THRESHOLD = 20
    return {
        'is_dangerous': is_dangerous,
        'dangerous_match': dangerous_match,
        'direct_subdirs': direct_subdirs,
        'large_folder': direct_subdirs > LARGE_FOLDER_THRESHOLD,
    }


def create_project(name: str, raw_path: str) -> dict:
    path = resolve_allowed_path(raw_path)
    if not path.is_dir():
        raise ValueError('Project path must be a directory.')
    now = utc_now()
    with transaction() as conn:
        cur = conn.execute(
            'INSERT INTO projects(name,path,created_at,status) VALUES(?,?,?,?)',
            (name.strip(), str(path), now, 'pending')
        )
        project_id = cur.lastrowid
        conn.execute(
            'INSERT INTO audit_log(project_id,action,detail,created_at) VALUES(?,?,?,?)',
            (project_id, 'project.created', str(path), now)
        )
    return get_project(project_id)


def list_files(project_id: int) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            '''SELECT id,relative_path,extension,size_bytes,indexed_at FROM files
               WHERE project_id=? ORDER BY relative_path''', (project_id,)
        ).fetchall()
    return [dict(row) for row in rows]


def read_project_file(project_id: int, relative_path: str) -> dict:
    project = get_project(project_id)
    path = safe_join(Path(project['path']), relative_path)
    if path.stat().st_size > settings.max_file_mb * 1024 * 1024:
        raise ValueError('File exceeds the configured direct-read limit.')
    content = path.read_text(encoding='utf-8', errors='replace')
    return {'relative_path': relative_path, 'content': content, 'size_bytes': path.stat().st_size}


def _fts_query(query: str) -> str:
    tokens = re.findall(r'[\w\-\.]+', query, flags=re.UNICODE)
    return ' OR '.join(f'"{token}"' for token in tokens[:12]) or '""'


def _locate_excerpt(content: str, query: str) -> int:
    """Best-effort character index of the most relevant excerpt in `content`.

    A natural-language query (e.g. "what database does this use?") is rarely a
    verbatim substring of file content, so a naive `content.find(query)` returns
    -1 and the excerpt collapses to the file head. We instead try, in order:
    the full phrase, then the first query token that actually occurs.
    """
    lowered = content.lower()
    exact = lowered.find(query.lower())
    if exact >= 0:
        return exact
    for token in re.findall(r'[\w\-]+', query, flags=re.UNICODE):
        if len(token) < 3:
            continue
        hit = lowered.find(token.lower())
        if hit >= 0:
            return hit
    return 0


# File-name pattern referenced inside a natural-language chat message, so the
# OCR tool can be dispatched from chat. Supports nested relative paths.
_FILE_REFERENCE_RE = re.compile(
    r'(?:[\w\-./\\]+\.(?:png|jpe?g|webp|bmp|tiff|pdf))',
    re.IGNORECASE,
)


def extract_file_reference(message: str) -> str | None:
    """Return the first supported file path mentioned in a chat message, or None.

    Used to dispatch deterministic tools (currently OCR) directly from chat
    instead of silently routing the request to the LLM.
    """
    match = _FILE_REFERENCE_RE.search(message)
    return match.group(0) if match else None


def search_project(project_id: int, query: str, limit: int = 8) -> list[dict]:
    fts = _fts_query(query)
    if not fts or fts == '""':
        return []
    with connect() as conn:
        try:
            rows = conn.execute(
                '''SELECT file_id,relative_path,
                   snippet(files_fts,0,'<mark>','</mark>',' … ',20) AS snippet,
                   bm25(files_fts) AS score
                   FROM files_fts WHERE files_fts MATCH ? AND project_id=?
                   ORDER BY score LIMIT ?''', (fts, project_id, limit)
            ).fetchall()
        except Exception:
            rows = []
    return [dict(row) for row in rows]


def list_memories(project_id: int) -> list[dict]:
    with connect() as conn:
        rows = conn.execute('SELECT * FROM memories WHERE project_id=? ORDER BY updated_at DESC', (project_id,)).fetchall()
    return [dict(row) for row in rows]


def create_memory(data: dict) -> dict:
    now = utc_now()
    with transaction() as conn:
        cur = conn.execute(
            '''INSERT INTO memories(project_id,kind,title,content,source,confidence,created_at,updated_at)
               VALUES(?,?,?,?,?,?,?,?)''',
            (data['project_id'], data['kind'], data['title'], data['content'], data['source'], data['confidence'], now, now)
        )
        row = conn.execute('SELECT * FROM memories WHERE id=?', (cur.lastrowid,)).fetchone()
    return dict(row)


def list_decisions(project_id: int) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            'SELECT * FROM decisions WHERE project_id=? ORDER BY created_at DESC', (project_id,)
        ).fetchall()
    return [dict(row) for row in rows]


def create_decision(data: dict) -> dict:
    now = utc_now()
    with transaction() as conn:
        if data.get('supersedes_id'):
            previous = conn.execute(
                'SELECT id,project_id,status FROM decisions WHERE id=?', (data['supersedes_id'],)
            ).fetchone()
            if not previous or previous['project_id'] != data['project_id']:
                raise ValueError('The superseded decision does not belong to this project.')
            conn.execute('UPDATE decisions SET status=? WHERE id=?', ('superseded', data['supersedes_id']))
        cur = conn.execute(
            '''INSERT INTO decisions(project_id,statement,rationale,status,supersedes_id,source,approved_by,created_at)
               VALUES(?,?,?,?,?,?,?,?)''',
            (data['project_id'], data['statement'], data['rationale'], 'active', data.get('supersedes_id'),
             data['source'], data['approved_by'], now)
        )
        row = conn.execute('SELECT * FROM decisions WHERE id=?', (cur.lastrowid,)).fetchone()
    return dict(row)


def build_context(project_id: int, query: str, max_chars: int = 12000) -> tuple[str, list[dict]]:
    citations = search_project(project_id, query, limit=6)
    decisions = [d for d in list_decisions(project_id) if d['status'] == 'active'][:8]
    memories = list_memories(project_id)[:8]
    sections: list[str] = []
    if decisions:
        sections.append('ACTIVE DECISIONS:\n' + '\n'.join(f"- D{d['id']}: {d['statement']}" for d in decisions))
    if memories:
        sections.append('PROJECT MEMORY:\n' + '\n'.join(f"- {m['kind']} / {m['title']}: {m['content'][:700]}" for m in memories))
    if citations:
        file_sections = []
        with connect() as conn:
            for item in citations:
                row = conn.execute('SELECT content FROM files WHERE id=?', (item['file_id'],)).fetchone()
                if row:
                    content = row['content']
                    index = _locate_excerpt(content, query)
                    excerpt = content[index - 500: index + 2500]
                    file_sections.append(f"SOURCE {item['relative_path']}:\n{excerpt}")
        sections.append('RELEVANT FILES:\n' + '\n\n'.join(file_sections))
    text = '\n\n'.join(sections)
    return text[:max_chars], citations


def list_relations(project_id: int, limit: int = 400) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            'SELECT * FROM relations WHERE project_id=? ORDER BY source_node,relation LIMIT ?', (project_id, limit)
        ).fetchall()
    return [dict(row) for row in rows]


def graph_query(project_id: int, node: str) -> dict:
    relations = list_relations(project_id, 5000)
    graph = nx.DiGraph()
    for rel in relations:
        graph.add_edge(rel['source_node'], rel['target_node'], relation=rel['relation'], confidence=rel['confidence'])
    matches = [n for n in graph.nodes if node.lower() in n.lower()]
    if not matches:
        return {'matches': [], 'neighbors': [], 'paths': []}
    selected = matches[0]
    neighbors = []
    for target in graph.successors(selected):
        neighbors.append({'direction': 'out', 'node': target, **graph.get_edge_data(selected, target)})
    for source in graph.predecessors(selected):
        neighbors.append({'direction': 'in', 'node': source, **graph.get_edge_data(source, selected)})
    return {'matches': matches[:20], 'selected': selected, 'neighbors': neighbors[:100]}


# ---- Graphify importer ----
#
# Maps a Graphify graph.json into the relations table. Graphify is a graph-
# memory SOURCE: its edges supplement (do not replace) the deterministic
# EXTRACTED relations produced by indexing. Imported edges are tagged
# confidence='INFERRED' so callers can tell provenance apart.

_RELATION_KEYS = ('relation', 'type', 'label', 'kind', 'relationship')
_EDGE_SOURCE_KEYS = ('source', 'from', 'src', 'start')
_EDGE_TARGET_KEYS = ('target', 'to', 'dst', 'end')


def map_graphify_edge(edge: dict) -> tuple[str, str, str, str] | None:
    """Normalize one Graphify edge into a relations row, or None if unusable.

    Returns (source_node, relation, target_node, evidence). Tolerates the
    common key variants Graphify emits across versions.
    """
    if not isinstance(edge, dict):
        return None
    source = next((str(edge[k]) for k in _EDGE_SOURCE_KEYS if edge.get(k)), '')
    target = next((str(edge[k]) for k in _EDGE_TARGET_KEYS if edge.get(k)), '')
    if not source or not target:
        return None
    relation = next((str(edge[k]) for k in _RELATION_KEYS if edge.get(k)), 'related') or 'related'
    evidence = str(edge.get('evidence') or edge.get('detail') or '')
    return source, relation, target, evidence[:300]


def _normalize_graphify_payload(data: dict) -> tuple[list, list]:
    """Defensive unwrap of Graphify graph.json node/edge containers.

    Tolerates a top-level 'graph' wrapper and nodes being either a list or an
    id-keyed dict. Edges may live under 'edges' or 'links'.
    """
    graph = data.get('graph') if isinstance(data.get('graph'), dict) else data
    nodes = graph.get('nodes') or data.get('nodes') or []
    if isinstance(nodes, dict):
        nodes = [{'id': key, **(val if isinstance(val, dict) else {})} for key, val in nodes.items()]
    edges = graph.get('links') or graph.get('edges') or data.get('links') or data.get('edges') or []
    return list(nodes), list(edges)


def import_graphify(project_id: int, graph_data: dict) -> dict:
    """Import a Graphify graph.json into the relations table.

    Each edge becomes a row tagged confidence='INFERRED'. Re-imports are
    idempotent via the UNIQUE(project_id, source_node, relation, target_node)
    constraint (INSERT OR IGNORE). Returns counts only — graph contents are
    never echoed to protect private project knowledge.

    Raises KeyError if the project does not exist.
    """
    # Validate the project exists (raises KeyError naturally).
    get_project(project_id)

    nodes, edges = _normalize_graphify_payload(graph_data)
    now = utc_now()
    imported = 0
    skipped = 0
    with transaction() as conn:
        for edge in edges:
            mapped = map_graphify_edge(edge)
            if mapped is None:
                skipped += 1
                continue
            source_node, relation, target_node, evidence = mapped
            cur = conn.execute(
                '''INSERT OR IGNORE INTO relations(project_id,source_node,relation,target_node,evidence,confidence)
                   VALUES(?,?,?,?,?,?)''',
                (project_id, source_node, relation, target_node, evidence, 'INFERRED')
            )
            if cur.rowcount:
                imported += 1
        # Audit log records only counts (privacy: no node/edge identifiers).
        conn.execute(
            'INSERT INTO audit_log(project_id,action,detail,created_at) VALUES(?,?,?,?)',
            (project_id, 'graph.imported', f'nodes={len(nodes)},edges={len(edges)},imported={imported},skipped={skipped}', now)
        )
    return {'nodes': len(nodes), 'edges': len(edges), 'imported': imported, 'skipped': skipped}


def create_write_proposal(project_id: int, relative_path: str, proposed_content: str) -> dict:
    project = get_project(project_id)
    root = Path(project['path'])
    path = safe_join(root, relative_path, must_exist=False)
    original = path.read_text(encoding='utf-8', errors='replace') if path.exists() else ''
    diff = ''.join(difflib.unified_diff(
        original.splitlines(keepends=True), proposed_content.splitlines(keepends=True),
        fromfile=f'a/{relative_path}', tofile=f'b/{relative_path}'
    ))
    now = utc_now()
    with transaction() as conn:
        cur = conn.execute(
            '''INSERT INTO write_proposals(project_id,relative_path,original_content,proposed_content,diff,status,created_at,original_sha256)
               VALUES(?,?,?,?,?,?,?,?)''',
            (project_id, relative_path, original, proposed_content, diff, 'pending', now,
             hashlib.sha256(original.encode('utf-8')).hexdigest())
        )
        row = conn.execute('SELECT * FROM write_proposals WHERE id=?', (cur.lastrowid,)).fetchone()
    return dict(row)


def list_write_proposals(project_id: int) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            'SELECT * FROM write_proposals WHERE project_id=? ORDER BY created_at DESC', (project_id,)
        ).fetchall()
    return [dict(row) for row in rows]


def apply_write_proposal(proposal_id: int) -> dict:
    with transaction() as conn:
        proposal = conn.execute('SELECT * FROM write_proposals WHERE id=?', (proposal_id,)).fetchone()
        if not proposal:
            raise KeyError('Proposal not found')
        if proposal['status'] != 'pending':
            raise ValueError('Only pending proposals can be applied.')
        project = conn.execute('SELECT * FROM projects WHERE id=?', (proposal['project_id'],)).fetchone()
        root = Path(project['path']).resolve()
        path = safe_join(root, proposal['relative_path'], must_exist=False)
        path.parent.mkdir(parents=True, exist_ok=True)
        current = path.read_text(encoding='utf-8', errors='replace') if path.exists() else ''
        current_hash = hashlib.sha256(current.encode('utf-8')).hexdigest()
        if proposal['original_sha256'] and current_hash != proposal['original_sha256']:
            raise ValueError('Stale write detected: the file changed after this proposal was created.')
        backup_path = None
        if path.exists():
            stamp = datetime.now().strftime('%d%m%y-%H%M%S')
            backup_path = path.with_name(f'{path.name}.backup.{stamp}')
            shutil.copy2(path, backup_path)
        fd, temp_name = tempfile.mkstemp(prefix=path.name + '.', suffix='.tmp', dir=str(path.parent))
        try:
            with os.fdopen(fd, 'w', encoding='utf-8', newline='') as handle:
                handle.write(proposal['proposed_content'])
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, path)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)
        now = utc_now()
        conn.execute(
            'UPDATE write_proposals SET status=?,backup_path=?,applied_at=? WHERE id=?',
            ('applied', str(backup_path) if backup_path else None, now, proposal_id)
        )
        conn.execute(
            'INSERT INTO audit_log(project_id,action,detail,created_at) VALUES(?,?,?,?)',
            (proposal['project_id'], 'file.write.applied', proposal['relative_path'], now)
        )
        row = conn.execute('SELECT * FROM write_proposals WHERE id=?', (proposal_id,)).fetchone()
    return dict(row)


def reject_write_proposal(proposal_id: int) -> dict:
    with transaction() as conn:
        conn.execute('UPDATE write_proposals SET status=? WHERE id=? AND status=?', ('rejected', proposal_id, 'pending'))
        row = conn.execute('SELECT * FROM write_proposals WHERE id=?', (proposal_id,)).fetchone()
    if not row:
        raise KeyError('Proposal not found')
    return dict(row)


def run_ocr(project_id: int, relative_path: str, language: str = 'eng') -> dict:
    project = get_project(project_id)
    path = safe_join(Path(project['path']), relative_path)
    suffix = path.suffix.lower()
    if suffix == '.pdf':
        reader = PdfReader(str(path))
        text = '\n\n'.join(page.extract_text() or '' for page in reader.pages)
        return {'engine': 'pypdf', 'text': text, 'confidence': None, 'pages': len(reader.pages)}
    if suffix not in {'.png', '.jpg', '.jpeg', '.webp', '.bmp', '.tiff'}:
        raise ValueError('OCR supports PDF and common image formats.')
    binary = shutil.which('tesseract')
    if not binary:
        raise RuntimeError('Tesseract is not installed. See docs/ocr.md.')
    result = subprocess.run(
        [binary, str(path), 'stdout', '-l', language], capture_output=True, text=True, timeout=120
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or 'Tesseract failed.')
    return {'engine': 'tesseract', 'text': result.stdout, 'confidence': None, 'pages': 1}


def simulate_image(project_id: int, prompt: str, width: int, height: int, seed: int) -> dict:
    project = get_project(project_id)
    root = Path(project['path']) / '.inmyai' / 'generated'
    root.mkdir(parents=True, exist_ok=True)
    actual_seed = seed if seed >= 0 else random.randint(0, 2_147_483_647)
    filename = f'image-simulation-{actual_seed}.png'
    output = root / filename
    image = Image.new('RGB', (width, height), '#f5f7fa')
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((24, 24, width - 24, height - 24), radius=24, fill='#ffffff', outline='#dfe4ea', width=2)
    draw.text((48, 48), 'InMyAI Image Router — Simulator', fill='#151a22')
    wrapped = []
    words = prompt.split()
    line = ''
    for word in words:
        if len(line) + len(word) > max(20, width // 11):
            wrapped.append(line)
            line = word
        else:
            line = f'{line} {word}'.strip()
    if line:
        wrapped.append(line)
    draw.multiline_text((48, 110), '\n'.join(wrapped[:12]), fill='#4e5866', spacing=8)
    draw.text((48, height - 70), f'Seed {actual_seed} • Not an AI-generated image', fill='#8b94a2')
    image.save(output)
    return {
        'provider': 'simulator', 'path': str(output), 'relative_path': output.relative_to(Path(project['path'])).as_posix(),
        'seed': actual_seed, 'notice': 'Not an AI-generated image. This deterministic preview verifies the workflow; configure ComfyUI or the optional Diffusers plugin for real local AI generation.'
    }


def hardware_snapshot() -> dict:
    vm = psutil.virtual_memory()
    disk = psutil.disk_usage(str(settings.data_dir.resolve()))
    return {
        'cpu': {'physical_cores': psutil.cpu_count(logical=False), 'logical_cores': psutil.cpu_count(), 'percent': psutil.cpu_percent(interval=0.1)},
        'ram': {'total_gb': round(vm.total / 1024**3, 2), 'available_gb': round(vm.available / 1024**3, 2), 'percent': vm.percent},
        'storage': {'total_gb': round(disk.total / 1024**3, 2), 'free_gb': round(disk.free / 1024**3, 2), 'percent': disk.percent},
        'profile': 'lite' if vm.total < 12 * 1024**3 else 'standard',
        'guard': {'allow_new_engine': vm.available > 1.5 * 1024**3, 'max_active_models': 1}
    }


def get_index_status(project_id: int) -> dict:
    """Combined view of a project's indexing status for UI polling.

    Joins projects.status with the index_progress row so the frontend can
    drive a progress bar from one cheap read.
    """
    with connect() as conn:
        project = conn.execute('SELECT status, indexed_at FROM projects WHERE id=?', (project_id,)).fetchone()
        if not project:
            raise KeyError('Project not found')
        prog = conn.execute(
            'SELECT phase,total_files,processed_files,error FROM index_progress WHERE project_id=?',
            (project_id,)
        ).fetchone()
    return {
        'status': project['status'],
        'phase': prog['phase'] if prog else ('done' if project['indexed_at'] else 'idle'),
        'total_files': prog['total_files'] if prog else 0,
        'processed_files': prog['processed_files'] if prog else 0,
        'error': prog['error'] if prog else None,
        'indexed_at': project['indexed_at'],
    }


def reset_interrupted_indexing() -> None:
    """Startup recovery: any project left in 'indexing' from a crashed run is
    moved back to 'pending' with a recorded 'interrupted' failure, so the UI
    offers a Retry instead of looking permanently stuck."""
    now = utc_now()
    with transaction() as conn:
        stuck = conn.execute("SELECT id FROM projects WHERE status='indexing'").fetchall()
        for row in stuck:
            conn.execute("UPDATE projects SET status='pending' WHERE id=?", (row['id'],))
            conn.execute(
                "INSERT INTO index_progress(project_id,phase,total_files,processed_files,started_at,updated_at,error) "
                "VALUES(?,?,?,?,?,?,?) "
                "ON CONFLICT(project_id) DO UPDATE SET phase='failed',error=excluded.error,updated_at=excluded.updated_at",
                (row['id'], 'failed', 0, 0, now, now, 'interrupted: indexing did not complete'),
            )
