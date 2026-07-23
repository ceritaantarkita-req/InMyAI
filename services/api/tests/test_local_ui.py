"""The dependency-free local UI (apps/local-ui) mounted at /app by main.py.

Ported from InMyAI v2: a plain HTML/JS/CSS fallback that needs no Node/npm
install, served directly by the FastAPI process for zero-friction first run.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from services.api.app.main import app

client = TestClient(app)


def test_local_ui_index_is_served() -> None:
    response = client.get('/app/')
    assert response.status_code == 200
    assert 'InMyAI' in response.text


def test_local_ui_assets_are_served() -> None:
    js_response = client.get('/app/app.js')
    assert js_response.status_code == 200
    css_response = client.get('/app/styles.css')
    assert css_response.status_code == 200
