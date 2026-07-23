"""Smoke-test the FastAPI app in-process and (re)write SMOKE_REPORT.json.

Boots the real `app` object via FastAPI's TestClient (no live server/port
needed) against a throwaway data dir + workspace, registers the bundled
`examples/synthetic-project`, and exercises the core HTTP surface: health,
hardware, project registration, indexing, search, chat (Safe Mock), and
model-runtime status - plus the multi-agent task pipeline
(agents/tasks/run) added during the v1/v2 merge, which the original
SMOKE_REPORT.json predates.

Run after touching main.py, services.py, or agent_runtime.py:

    python3 scripts/smoke_check.py
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

_TEMP = ROOT / '.smoke-runtime'
if _TEMP.exists():
    shutil.rmtree(_TEMP, ignore_errors=True)
_TEMP.mkdir(parents=True, exist_ok=True)

from services.api.app.config import settings  # noqa: E402

settings.data_dir = _TEMP / 'data'
settings.workspace_root = _TEMP / 'workspace'
settings.allow_any_local_path = True
settings.ensure_dirs()

from services.api.app.database import migrate  # noqa: E402

migrate()

from fastapi.testclient import TestClient  # noqa: E402

from services.api.app.main import app  # noqa: E402

client = TestClient(app)
checks: list[dict] = []


def call(method: str, path: str, **kwargs) -> "TestClient":
    response = client.request(method, path, **kwargs)
    checks.append({'method': method, 'path': path, 'status': response.status_code})
    return response


def main() -> dict:
    example_path = ROOT / 'examples' / 'synthetic-project'

    call('GET', '/api/health')
    hardware = call('GET', '/api/hardware')
    project = call('POST', '/api/projects', json={'name': 'Synthetic demo', 'path': str(example_path)}).json()
    call('GET', '/api/projects')
    index_result = call('POST', f"/api/projects/{project['id']}/index").json()
    search_result = call('POST', '/api/search', json={'project_id': project['id'], 'query': 'canOpenAdmin', 'limit': 5}).json()
    chat_result = call('POST', '/api/chat', json={
        'project_id': project['id'], 'message': 'What does this project do?',
        'conversation_id': None, 'provider': 'mock',
    }).json()
    models_status = call('GET', '/api/models/status').json()

    # Multi-agent task pipeline (ported from v2 during the v1/v2 merge).
    call('GET', f"/api/projects/{project['id']}/agents")
    task = call('POST', '/api/tasks', json={
        'project_id': project['id'], 'title': 'Smoke task',
        'instruction': 'Summarize this project in one sentence.', 'provider': 'mock',
    }).json()
    task_detail = call('POST', f"/api/tasks/{task['id']}/run").json()

    report = {
        'passed': all(check['status'] < 400 for check in checks),
        'checks': checks,
        'project': project['name'],
        'index': index_result,
        'search_hits': len(search_result.get('results', [])),
        'chat_provider': chat_result.get('provider'),
        'chat_citations': len(chat_result.get('citations', [])),
        'hardware_profile': hardware.json().get('profile'),
        'ollama_available': models_status.get('ollama', {}).get('available', False),
        'agent_task_status': task_detail.get('task', {}).get('status'),
        'agent_task_events': [event['state'] for event in task_detail.get('events', [])],
    }
    return report


if __name__ == '__main__':
    result = main()
    out_path = ROOT / 'SMOKE_REPORT.json'
    out_path.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    shutil.rmtree(_TEMP, ignore_errors=True)
    print(json.dumps(result, indent=2))
    sys.exit(0 if result['passed'] else 1)
