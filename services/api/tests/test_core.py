from __future__ import annotations

import os
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from services.api.app.config import settings
from services.api.app.database import migrate
from services.api.app.main import app
from services.api.app.providers import choose_ollama_model
from services.api.app.image_provider import replace_placeholders, find_first_image


def setup_module() -> None:
    root = Path('/tmp/inmyai-tests')
    if root.exists():
        import shutil
        shutil.rmtree(root)
    settings.data_dir = root / 'data'
    settings.workspace_root = root / 'workspace'
    settings.allow_any_local_path = False
    settings.ensure_dirs()
    project = settings.workspace_root / 'demo'
    project.mkdir(parents=True)
    (project / 'README.md').write_text('# Demo\n\nThe active database is SQLite.\n', encoding='utf-8')
    (project / 'main.ts').write_text("import { login } from './auth'\nexport function run(){ return login() }\n", encoding='utf-8')
    (project / 'auth.ts').write_text('export function login(){ return true }\n', encoding='utf-8')
    image = Image.new('RGB', (500, 160), 'white')
    ImageDraw.Draw(image).text((20, 50), 'INVOICE 2026 TEST', fill='black')
    image.save(project / 'invoice.png')
    migrate()


client = TestClient(app)


def create_demo_project() -> dict:
    projects = client.get('/api/projects').json()
    if projects:
        return projects[0]
    response = client.post('/api/projects', json={
        'name': 'Demo', 'path': str(settings.workspace_root / 'demo')
    })
    assert response.status_code == 200, response.text
    return response.json()


def test_health_and_hardware() -> None:
    assert client.get('/api/health').json()['ok'] is True
    snapshot = client.get('/api/hardware').json()
    assert snapshot['ram']['total_gb'] > 0
    assert snapshot['guard']['max_active_models'] == 1


def test_project_index_search_and_graph() -> None:
    project = create_demo_project()
    result = client.post(f"/api/projects/{project['id']}/index")
    assert result.status_code == 200, result.text
    assert result.json()['indexed'] >= 3
    search = client.post('/api/search', json={'project_id': project['id'], 'query': 'SQLite'}).json()
    assert search['results'][0]['relative_path'] == 'README.md'
    graph = client.get(f"/api/projects/{project['id']}/graph", params={'node': 'main.ts'}).json()
    assert graph['selected'] == 'main.ts'
    assert any(n['relation'] == 'imports' for n in graph['neighbors'])


def test_memory_and_decision_supersession() -> None:
    project = create_demo_project()
    memory = client.post('/api/memories', json={
        'project_id': project['id'], 'kind': 'semantic', 'title': 'Framework',
        'content': 'The project uses TypeScript.', 'source': 'test', 'confidence': 1
    })
    assert memory.status_code == 200
    first = client.post('/api/decisions', json={
        'project_id': project['id'], 'statement': 'Use SQLite', 'rationale': 'Lightweight'
    }).json()
    second = client.post('/api/decisions', json={
        'project_id': project['id'], 'statement': 'Use PostgreSQL', 'rationale': 'Production',
        'supersedes_id': first['id']
    }).json()
    decisions = client.get(f"/api/projects/{project['id']}/decisions").json()
    old = next(d for d in decisions if d['id'] == first['id'])
    assert old['status'] == 'superseded'
    assert second['status'] == 'active'


def test_write_proposal_backup_and_apply() -> None:
    project = create_demo_project()
    response = client.post('/api/proposals', json={
        'project_id': project['id'], 'relative_path': 'auth.ts',
        'proposed_content': 'export function login(){ return false }\n'
    })
    assert response.status_code == 200, response.text
    proposal = response.json()
    assert '-export function login(){ return true }' in proposal['diff']
    applied = client.post(f"/api/proposals/{proposal['id']}/apply")
    assert applied.status_code == 200
    assert Path(applied.json()['backup_path']).exists()
    assert 'false' in (settings.workspace_root / 'demo' / 'auth.ts').read_text()


def test_ocr_and_image_simulator() -> None:
    project = create_demo_project()
    ocr = client.post('/api/ocr', json={
        'project_id': project['id'], 'relative_path': 'invoice.png', 'language': 'eng'
    })
    assert ocr.status_code == 200, ocr.text
    assert 'INVOICE' in ocr.json()['text'].upper()
    image = client.post('/api/images/generate', json={
        'project_id': project['id'], 'prompt': 'navy industrial coverall',
        'width': 512, 'height': 512, 'provider': 'simulator'
    })
    assert image.status_code == 200, image.text
    assert Path(image.json()['path']).exists()
    assert 'Not an AI-generated image' in image.json()['notice']


def test_chat_safe_mock_and_citations() -> None:
    project = create_demo_project()
    client.post(f"/api/projects/{project['id']}/index")
    response = client.post('/api/chat', json={
        'project_id': project['id'], 'message': 'What database does this project use?', 'provider': 'mock'
    })
    assert response.status_code == 200, response.text
    body = response.json()
    assert body['provider'] == 'mock'
    assert body['conversation_id'] > 0
    assert body['citations']


def test_model_router_prefers_small_coding_model() -> None:
    models = [
        {'name': 'gemma3:4b', 'size': 3_300_000_000},
        {'name': 'qwen2.5-coder:3b', 'size': 2_000_000_000},
        {'name': 'qwen2.5-coder:7b', 'size': 4_700_000_000}
    ]
    assert choose_ollama_model('coding', models) == 'qwen2.5-coder:3b'
    assert choose_ollama_model('general', models) == 'gemma3:4b'


def test_comfyui_workflow_helpers() -> None:
    workflow = {'6': {'inputs': {'text': '{{PROMPT}}', 'seed': '{{SEED}}'}}, 'list': ['{{WIDTH}}']}
    replaced = replace_placeholders(workflow, {'PROMPT': 'navy coverall', 'SEED': 42, 'WIDTH': 512})
    assert replaced['6']['inputs']['text'] == 'navy coverall'
    assert replaced['6']['inputs']['seed'] == '42'
    history = {'outputs': {'9': {'images': [{'filename': 'out.png', 'type': 'output'}]}}}
    assert find_first_image(history)['filename'] == 'out.png'
