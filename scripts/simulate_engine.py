from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient
from services.api.app.config import settings
from services.api.app.database import migrate
from services.api.app.main import app


def run_cycle(index: int) -> dict:
    root = Path(f'/tmp/inmyai-simulation-{index}')
    if root.exists():
        shutil.rmtree(root)
    settings.data_dir = root / 'data'
    settings.workspace_root = root / 'workspace'
    settings.allow_any_local_path = False
    settings.ensure_dirs()
    project_dir = settings.workspace_root / 'demo'
    project_dir.mkdir(parents=True)
    (project_dir / 'README.md').write_text(
        '# Demo\n\nActive database decision: SQLite.\nThe app must remain local-first.\n',
        encoding='utf-8'
    )
    (project_dir / 'main.py').write_text('def answer():\n    return 42\n', encoding='utf-8')
    migrate()
    client = TestClient(app)

    project = client.post('/api/projects', json={'name': f'Demo {index}', 'path': str(project_dir)}).json()
    indexed = client.post(f"/api/projects/{project['id']}/index").json()
    decision = client.post('/api/decisions', json={
        'project_id': project['id'], 'statement': 'Use SQLite', 'rationale': 'Low memory footprint'
    }).json()
    task = client.post('/api/tasks', json={
        'project_id': project['id'],
        'title': 'Verify local architecture',
        'instruction': 'Explain the active database decision using only project evidence.',
        'provider': 'mock'
    }).json()
    task_result = client.post(f"/api/tasks/{task['id']}/run").json()
    proposal = client.post('/api/proposals', json={
        'project_id': project['id'],
        'relative_path': 'main.py',
        'proposed_content': 'def answer():\n    return 43\n'
    }).json()
    applied = client.post(f"/api/proposals/{proposal['id']}/apply").json()

    assert indexed['errors'] == []
    assert decision['status'] == 'active'
    assert task_result['task']['status'] == 'completed'
    assert Path(task_result['task']['artifact_path']).exists()
    assert applied['status'] == 'applied'
    assert '43' in (project_dir / 'main.py').read_text(encoding='utf-8')

    return {
        'cycle': index,
        'index': indexed,
        'task_status': task_result['task']['status'],
        'events': [event['state'] for event in task_result['events']],
        'proposal_status': applied['status'],
        'backup_exists': bool(applied.get('backup_path') and Path(applied['backup_path']).exists()),
    }


if __name__ == '__main__':
    report = {'ok': True, 'cycles': []}
    for i in range(1, 4):
        report['cycles'].append(run_cycle(i))
    out = Path('docs/qa/ENGINE_SIMULATION_3X.json')
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))
