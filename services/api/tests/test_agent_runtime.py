"""Multi-agent task orchestration (Coordinator -> Researcher -> Worker -> Verifier).

Ported from InMyAI v2's agent_runtime.py. The four logical agents share one
project's context (files, decisions, memories); a task runs a fixed pipeline
and checkpoints every state transition to `agent_events` so progress survives
a restart. `provider: 'mock'` keeps this deterministic and offline, same
convention used everywhere else in this codebase (see providers.py).
"""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from services.api.app.config import settings
from services.api.app.main import app

client = TestClient(app)


def _demo_project() -> dict:
    """Reuse the shared demo project if another test already created it,
    otherwise register it. Mirrors create_demo_project() in test_core.py so
    this file also passes when run standalone (pytest test_agent_runtime.py),
    not just as part of the full suite where test ordering happens to help."""
    rows = client.get('/api/projects').json()
    if rows:
        return rows[0]
    response = client.post('/api/projects', json={
        'name': 'Demo', 'path': str(settings.workspace_root / 'demo')
    })
    assert response.status_code == 200, response.text
    return response.json()


def test_agents_are_seeded_lazily_on_first_read() -> None:
    project = _demo_project()
    response = client.get(f"/api/projects/{project['id']}/agents")
    assert response.status_code == 200, response.text
    agents = response.json()
    slugs = {a['slug'] for a in agents}
    assert {'coordinator', 'researcher', 'worker', 'verifier'} <= slugs
    assert all(a['status'] == 'idle' for a in agents)


def test_agent_task_run_and_checkpoint_sequence() -> None:
    project = _demo_project()
    created = client.post('/api/tasks', json={
        'project_id': project['id'],
        'title': 'Grounded note',
        'instruction': 'Explain the active database decision using indexed evidence.',
        'provider': 'mock',
    })
    assert created.status_code == 200, created.text
    task_id = created.json()['id']

    result = client.post(f'/api/tasks/{task_id}/run')
    assert result.status_code == 200, result.text
    body = result.json()
    assert body['task']['status'] == 'completed'
    assert Path(body['task']['artifact_path']).exists()

    states = [event['state'] for event in body['events']]
    assert states == ['queued', 'planning', 'retrieving', 'running_tool', 'verifying', 'completed']

    # Detail endpoint must return the same checkpointed state on a fresh read.
    detail = client.get(f'/api/tasks/{task_id}').json()
    assert detail['task']['status'] == 'completed'
    assert len(detail['events']) == len(body['events'])


def test_task_not_found_returns_404() -> None:
    response = client.get('/api/tasks/999999')
    assert response.status_code == 404


def test_cancel_task_records_event() -> None:
    project = _demo_project()
    created = client.post('/api/tasks', json={
        'project_id': project['id'], 'title': 'To be cancelled',
        'instruction': 'Placeholder instruction long enough to pass validation.', 'provider': 'mock'
    }).json()
    cancelled = client.post(f"/api/tasks/{created['id']}/cancel")
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()['task']['status'] == 'cancelled'
