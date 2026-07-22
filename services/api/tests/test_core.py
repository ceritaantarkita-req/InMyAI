from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from services.api.app.config import settings
from services.api.app.indexer import index_project
from services.api.app.main import app
from services.api.app.providers import choose_ollama_model
from services.api.app.services import build_context, extract_file_reference
from services.api.app.image_provider import replace_placeholders, find_first_image


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


def test_build_context_locates_relevant_excerpt_not_file_start() -> None:
    """When FTS finds a file, the excerpt must locate the matching token,
    not blindly slice from the file's first character.

    Regression: build_context used `content.find(query)` on the full multi-word
    query, which returns -1 almost always (a natural-language question is not a
    verbatim substring of file content), so the excerpt always started at 0.
    """
    project = create_demo_project()
    # The matching marker sits well past the first 2500 chars so a bug that
    # always slices content[0:2500] would miss it entirely.
    marker = 'ZIRCONIUM_GATEWAY_DECISION'
    filler = ('lorem ipsum dolor sit amet. ' * 150)  # ~3600 chars of filler
    notes_path = settings.workspace_root / 'demo' / 'deep_notes.md'
    notes_path.write_text(
        f'# Deep notes\n\n{filler}\n\nThe active marker is {marker}.\n',
        encoding='utf-8'
    )
    index_project(project['id'], settings.workspace_root / 'demo')
    # A natural-language question: FTS still finds the file via the token, but
    # the full string is NOT a verbatim substring, so the old `.find()` hits -1.
    context, citations = build_context(
        project['id'], 'what is the zirconium gateway decision about?', max_chars=6000
    )
    assert citations, 'FTS should find the file containing the marker'
    assert marker in context, (
        'Excerpt must locate the matching token in the file body, '
        'not return the file head. Got excerpt missing the marker.'
    )


def test_extract_file_reference_finds_supported_path() -> None:
    assert extract_file_reference('please OCR invoice.png') == 'invoice.png'
    assert extract_file_reference('scan src/scan.pdf for me') == 'src/scan.pdf'
    assert extract_file_reference('look at IMG_001.JPG') == 'IMG_001.JPG'
    assert extract_file_reference('no file mentioned here') is None


def test_chat_dispatches_ocr_when_path_present() -> None:
    """A chat message that names an indexed image must run the OCR tool, not Mock."""
    project = create_demo_project()
    response = client.post('/api/chat', json={
        'project_id': project['id'], 'message': 'ocr invoice.png', 'provider': 'auto'
    })
    assert response.status_code == 200, response.text
    body = response.json()
    assert body['provider'] == 'local-tool', body
    assert body['route']['engine'] == 'tesseract'
    assert 'INVOICE' in body['answer'].upper(), body['answer']


def test_chat_ocr_without_path_returns_guidance() -> None:
    """OCR intent without a file path must stay local-tool and guide the user."""
    project = create_demo_project()
    response = client.post('/api/chat', json={
        'project_id': project['id'], 'message': 'ocr this document', 'provider': 'auto'
    })
    assert response.status_code == 200, response.text
    body = response.json()
    assert body['provider'] == 'local-tool', body
    # Must point the user at how to specify a file, not silently mock.
    assert 'file' in body['answer'].lower() or 'studio' in body['answer'].lower(), body['answer']


def test_chat_ocr_missing_file_is_graceful() -> None:
    """A named-but-absent file must not 500; it returns local-tool guidance."""
    project = create_demo_project()
    response = client.post('/api/chat', json={
        'project_id': project['id'], 'message': 'ocr doesnotexist.png', 'provider': 'auto'
    })
    assert response.status_code == 200, response.text
    body = response.json()
    assert body['provider'] == 'local-tool', body
    assert 'doesnotexist.png' in body['answer'], body['answer']


def test_chat_diff_task_returns_guidance_not_mock() -> None:
    """Diff/image tool tasks must surface honest guidance, not run the Mock LLM."""
    project = create_demo_project()
    response = client.post('/api/chat', json={
        'project_id': project['id'], 'message': 'diff these two files for me', 'provider': 'auto'
    })
    assert response.status_code == 200, response.text
    body = response.json()
    assert body['provider'] == 'local-tool', body
    assert body['provider'] != 'mock'
    assert 'file' in body['answer'].lower(), body['answer']
