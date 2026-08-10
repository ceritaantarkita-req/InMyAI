from __future__ import annotations

from fastapi.testclient import TestClient

from services.api.app.main import app


client = TestClient(app)


def test_health_is_minimal_and_does_not_leak_database_path() -> None:
    response = client.get('/api/health')
    assert response.status_code == 200
    body = response.json()
    assert body == {
        'ok': True,
        'app': 'InMyAI',
        'version': '0.1.0',
        'mode': 'local-first',
        'status': 'healthy',
    }
    assert 'database' not in body


def test_manifest_is_raw_and_keeps_r0_separate_from_terminal_r3() -> None:
    response = client.get('/api/inmy/manifest')
    assert response.status_code == 200
    manifest = response.json()
    assert manifest['schemaVersion'] == '1.0.0'
    assert manifest['canonicalId'] == 'inmyai'
    assert 'success' not in manifest
    assert isinstance(manifest['data'], dict)
    assert manifest['data']['policy'] == 'local-only'

    by_id = {item['id']: item for item in manifest['capabilities']}
    assert by_id['ai.project.search']['riskClass'] == 'R0'
    assert by_id['ai.project.search']['mode'] == 'read'
    assert by_id['ai.project.search']['approvalRequired'] is False
    assert by_id['ai.terminal.execute']['riskClass'] == 'R3'
    assert by_id['ai.terminal.execute']['mode'] == 'execute'
    assert by_id['ai.terminal.execute']['approvalRequired'] is True


def test_http_authority_rejects_public_host_and_private_lan_origin() -> None:
    blocked_host = client.get('/api/health', headers={'host': 'attacker.example'})
    assert blocked_host.status_code == 403
    assert blocked_host.json()['code'] == 'LOCAL_HOST_REQUIRED'

    blocked_origin = client.get(
        '/api/health',
        headers={'origin': 'http://192.168.1.50:3000'},
    )
    assert blocked_origin.status_code == 403
    assert blocked_origin.json()['code'] == 'LOCAL_ORIGIN_REQUIRED'


def test_loopback_and_tauri_browser_origins_are_authorized() -> None:
    for origin in (
        'http://127.0.0.1:3000',
        'http://localhost:3000',
        'http://127.0.0.1:17001',
        'http://localhost:17001',
        'http://127.0.0.1:8000',
        'http://localhost:8000',
        'http://tauri.localhost',
        'https://tauri.localhost',
        'tauri://localhost',
    ):
        response = client.get('/api/health', headers={'origin': origin})
        assert response.status_code == 200, origin
