from fastapi.testclient import TestClient

from services.api.app.main import app


def test_managed_lifecycle_shutdown_is_token_bound_and_disabled_by_default(monkeypatch):
    monkeypatch.delenv('INMY_LIFECYCLE_SHUTDOWN_TOKEN', raising=False)
    requested: list[bool] = []
    app.state.lifecycle_shutdown = lambda: requested.append(True)
    app.state.lifecycle_shutdown_requested = False

    with TestClient(app) as client:
        response = client.post('/api/internal/lifecycle/shutdown')
        assert response.status_code == 404

        monkeypatch.setenv('INMY_LIFECYCLE_SHUTDOWN_TOKEN', 'manager-generated-test-token')
        response = client.post(
            '/api/internal/lifecycle/shutdown',
            headers={'Authorization': 'Bearer wrong-token'},
        )
        assert response.status_code == 403
        assert requested == []

        response = client.post(
            '/api/internal/lifecycle/shutdown',
            headers={'Authorization': 'Bearer manager-generated-test-token'},
        )
        assert response.status_code == 202
        assert response.json() == {'accepted': True}
        assert requested == [True]
