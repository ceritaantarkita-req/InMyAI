from __future__ import annotations

import itertools
from pathlib import Path

from services.api.app import services
from services.api.app.config import settings
from services.api.app.database import connect

# Projects must live under an allowed root (workspace_root), not pytest's
# tmp_path under the user profile (which the policy layer blocks).
_counter = itertools.count(1000)


def _make_project(name: str) -> dict:
    path = settings.workspace_root / f'graphify-{next(_counter)}-{name}'
    path.mkdir(parents=True, exist_ok=True)
    return services.create_project(name, str(path))


def _relation_rows(project_id: int) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            'SELECT source_node, relation, target_node, evidence, confidence '
            'FROM relations WHERE project_id=? AND confidence=? '
            'ORDER BY source_node, target_node',
            (project_id, 'INFERRED'),
        ).fetchall()
    return [dict(r) for r in rows]


def _audit_rows(project_id: int) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            'SELECT action, detail FROM audit_log WHERE project_id=? ORDER BY id DESC',
            (project_id,),
        ).fetchall()
    return [dict(r) for r in rows]


# ---------- pure helper: map_graphify_edge ----------

def test_map_edge_handles_source_target_relation_keys() -> None:
    edge = {'source': 'app.ts', 'target': 'auth.ts', 'relation': 'imports'}
    row = services.map_graphify_edge(edge)
    assert row is not None
    source_node, relation, target_node, _evidence = row
    assert source_node == 'app.ts'
    assert target_node == 'auth.ts'
    assert relation == 'imports'


def test_map_edge_accepts_alternate_key_names() -> None:
    # Graphify variants use 'from'/'to' and 'type'/'label'/'kind'.
    edge = {'from': 'a', 'to': 'b', 'label': 'calls'}
    row = services.map_graphify_edge(edge)
    assert row == ('a', 'calls', 'b', '')


def test_map_edge_defaults_relation_when_missing() -> None:
    edge = {'source': 'a', 'target': 'b'}  # no relation/type/label
    row = services.map_graphify_edge(edge)
    assert row is not None
    assert row[1] == 'related'  # default relation


def test_map_edge_skips_edges_without_both_endpoints() -> None:
    assert services.map_graphify_edge({'source': 'a', 'relation': 'imports'}) is None
    assert services.map_graphify_edge({'target': 'b', 'relation': 'imports'}) is None
    assert services.map_graphify_edge({}) is None


# ---------- services.import_graphify integration ----------

def test_import_graphify_inserts_inferred_relations_and_audits() -> None:
    project = _make_project('test')
    graph_data = {
        'nodes': [{'id': 'app.ts'}, {'id': 'auth.ts'}],
        'edges': [
            {'source': 'app.ts', 'target': 'auth.ts', 'relation': 'imports'},
            {'source': 'app.ts', 'target': 'db.ts', 'relation': 'calls'},
        ],
    }
    result = services.import_graphify(project['id'], graph_data)
    assert result['imported'] == 2
    assert result['skipped'] == 0

    rows = _relation_rows(project['id'])
    assert len(rows) == 2
    rels = {(r['source_node'], r['relation'], r['target_node']) for r in rows}
    assert ('app.ts', 'imports', 'auth.ts') in rels
    assert ('app.ts', 'calls', 'db.ts') in rels

    # audit log records the import with counts (no graph content echoed)
    audit = _audit_rows(project['id'])
    assert audit[0]['action'] == 'graph.imported'
    assert 'imported=2' in audit[0]['detail']
    # privacy: graph node/edge identifiers must not be echoed in audit detail
    assert 'app.ts' not in audit[0]['detail']


def test_import_graphify_is_idempotent_on_reimport() -> None:
    project = _make_project('idem')
    graph_data = {
        'edges': [{'source': 'a', 'target': 'b', 'relation': 'imports'}],
    }
    services.import_graphify(project['id'], graph_data)
    second = services.import_graphify(project['id'], graph_data)
    # UNIQUE(project_id, source_node, relation, target_node) dedups; second run
    # re-attempts both but the inserted count reflects only the new rows (0).
    rows = _relation_rows(project['id'])
    assert len(rows) == 1


def test_import_graphify_handles_wrapper_shapes() -> None:
    # graph.json may be wrapped under 'graph' and use dict nodes.
    project = _make_project('wrap')
    graph_data = {
        'graph': {
            'nodes': {'a': {}, 'b': {}},
            'links': [{'source': 'a', 'target': 'b', 'type': 'imports'}],
        }
    }
    result = services.import_graphify(project['id'], graph_data)
    assert result['imported'] == 1
    rows = _relation_rows(project['id'])
    assert len(rows) == 1
    assert rows[0]['relation'] == 'imports'


def test_import_graphify_unknown_project_raises() -> None:
    import pytest
    graph_data = {'edges': [{'source': 'a', 'target': 'b', 'relation': 'imports'}]}
    with pytest.raises(KeyError):
        services.import_graphify(999999, graph_data)


def test_import_graphify_imported_relations_are_graph_queryable() -> None:
    project = _make_project('query')
    services.import_graphify(project['id'], {
        'edges': [{'source': 'svc.ts', 'target': 'repo.ts', 'relation': 'imports'}],
    })
    result = services.graph_query(project['id'], 'svc.ts')
    assert result['selected'] == 'svc.ts'
    out_targets = {n['node'] for n in result['neighbors'] if n['direction'] == 'out'}
    assert 'repo.ts' in out_targets


# ---------- HTTP endpoint: POST /api/projects/{id}/graph/import ----------

def test_graph_import_endpoint_accepts_graphify_json() -> None:
    """Phase 2 Task 3: the Graphify importer is now reachable over HTTP so the
    Graph tab UI can offer it as a real affordance, not just a footer caption."""
    from services.api.app.config import settings
    from fastapi.testclient import TestClient
    from services.api.app.main import app
    client = TestClient(app)
    projects = client.get('/api/projects').json()
    if not projects:
        root = settings.workspace_root / 'graphify_demo'
        root.mkdir(parents=True, exist_ok=True)
        proj = client.post('/api/projects', json={'name': 'Graphify', 'path': str(root)}).json()
        project_id = proj['id']
    else:
        project_id = projects[0]['id']
    payload = {
        'nodes': [{'id': 'a'}, {'id': 'b'}],
        'edges': [{'source': 'a', 'target': 'b', 'relation': 'depends_on'}],
    }
    response = client.post(f'/api/projects/{project_id}/graph/import', json=payload)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body['imported'] >= 1


def test_graph_import_endpoint_404_for_unknown_project() -> None:
    from fastapi.testclient import TestClient
    from services.api.app.main import app
    client = TestClient(app)
    response = client.post('/api/projects/999999/graph/import', json={'edges': []})
    assert response.status_code == 404
