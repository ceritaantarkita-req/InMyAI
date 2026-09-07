"""Q11.3 Piece 1 -- scenario_runtime.py: replayable deterministic scenario
(Phase 12 rung 1, see docs/plans/inmy_master_roadmap.md SS12).

Same async convention as the rest of this codebase's real tests
(test_connect_inmyrnd.py, test_connect_inmysandbox.py): plain
asyncio.run(...) inside sync test functions, no pytest-asyncio dependency.
"""
from __future__ import annotations

import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from services.api.app import scenario_runtime, services
from services.api.app.database import migrate, transaction, utc_now
from services.api.app import main
from services.api.app.main import app

client = TestClient(app)

SLUG = 'q11-3-context-recall-v1'

RUN_PAYLOAD = {'idempotency_key': 'scenario-runtime-http-test-0001'}


class _AlwaysSucceedsScenarioAuthorityClient:
    """Piece 3 (2026-09-04) gated these HTTP routes behind InMyHub's
    scenario-execution-r1 authority. This file's own job is testing
    scenario_runtime.py's real execution behavior end-to-end through the
    HTTP layer, not Hub governance itself (that is exhaustively covered by
    services/api/tests/test_scenario_run_endpoint.py's stub-based tests) --
    so every test here gets one permissive, always-succeeding stub rather
    than each test wiring its own.
    """

    async def authorize(self, **kwargs):
        return {'authorizationId': 'scenauth_' + '0' * 40}

    async def record_intent(self, **kwargs):
        return {'intentId': 'scenhubi_' + '0' * 40}

    async def record_execution(self, **kwargs):
        return {
            'receiptId': 'scenhubr_' + '0' * 40,
            'authorizationId': 'scenauth_' + '0' * 40,
            'outcome': kwargs['executor_receipt']['outcome'],
        }


@pytest.fixture(autouse=True)
def _stub_scenario_hub_authority(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main, '_scenario_authority_client', lambda: _AlwaysSucceedsScenarioAuthorityClient())



def setup_module() -> None:
    migrate()


# ---- scenario_runtime module, direct ----

def test_builtin_scenario_is_listed() -> None:
    scenarios = scenario_runtime.list_scenarios()
    slugs = {s['slug'] for s in scenarios}
    assert SLUG in slugs


def test_get_scenario_returns_variants_with_full_scripts() -> None:
    scenario = scenario_runtime.get_scenario(SLUG)
    payload = json.loads(scenario['script_json'])
    variants = payload['variants']
    assert len(variants) == 2
    for variant in variants:
        assert len(variant) == 3
        assert all({'title', 'instruction'} <= set(step) for step in variant)


def test_get_scenario_unknown_slug_raises_keyerror() -> None:
    with pytest.raises(KeyError):
        scenario_runtime.get_scenario('does-not-exist-v1')


def test_run_scenario_completes_with_three_steps() -> None:
    run = asyncio.run(scenario_runtime.run_scenario(SLUG))
    assert run['status'] == 'completed'
    assert run['trace_hash']
    task_ids = json.loads(run['task_ids_json'])
    assert len(task_ids) == 3
    trace = json.loads(run['trace_json'])
    assert len(trace['steps']) == 3
    for step in trace['steps']:
        assert step['states'] == ['queued', 'planning', 'retrieving', 'running_tool', 'verifying', 'completed']
        assert step['result_text_sha256']


def test_run_scenario_seeds_isolated_fixture_project_with_no_decisions() -> None:
    run = asyncio.run(scenario_runtime.run_scenario(SLUG))
    project = services.get_project(run['fixture_project_id'])
    assert project['name'] == f'scenario-fixture-{SLUG}'
    files = services.list_files(run['fixture_project_id'])
    assert [f['relative_path'] for f in files] == ['notes/architecture.md']
    memories = services.list_memories(run['fixture_project_id'])
    assert len(memories) == 1
    assert memories[0]['title'] == 'Scenario fixture purpose'
    # Deliberately no decisions -- see scenario_runtime.py's module
    # docstring for why (decision ids leak into MockProvider text and are
    # not stable across independently-seeded fixture projects).
    assert services.list_decisions(run['fixture_project_id']) == []


def test_two_runs_use_two_different_fixture_projects() -> None:
    run_a = asyncio.run(scenario_runtime.run_scenario(SLUG))
    run_b = asyncio.run(scenario_runtime.run_scenario(SLUG))
    assert run_a['fixture_project_id'] != run_b['fixture_project_id']


def test_two_runs_with_same_seed_produce_identical_trace_hash() -> None:
    """Rung-2 replacement for Rung-1's "always identical" guarantee: two
    independently-seeded fixture projects run with the SAME explicit seed
    must still produce byte-identical canonical traces (same seed -> same
    variant -> same trace), even though the fixture projects themselves
    are distinct."""
    run_a = asyncio.run(scenario_runtime.run_scenario(SLUG, seed=424242))
    run_b = asyncio.run(scenario_runtime.run_scenario(SLUG, seed=424242))
    assert run_a['fixture_project_id'] != run_b['fixture_project_id']
    assert run_a['trace_hash'] == run_b['trace_hash']


def test_two_runs_with_same_seed_match_step_by_step() -> None:
    run_a = asyncio.run(scenario_runtime.run_scenario(SLUG, seed=424242))
    run_b = asyncio.run(scenario_runtime.run_scenario(SLUG, seed=424242))
    steps_a = json.loads(run_a['trace_json'])['steps']
    steps_b = json.loads(run_b['trace_json'])['steps']
    assert len(steps_a) == len(steps_b) == 3
    for step_a, step_b in zip(steps_a, steps_b):
        assert step_a['result_text_sha256'] == step_b['result_text_sha256']
        assert step_a['verification'] == step_b['verification']


def test_verification_trace_excludes_volatile_subprocess_fields() -> None:
    run = asyncio.run(scenario_runtime.run_scenario(SLUG))
    trace = json.loads(run['trace_json'])
    for step in trace['steps']:
        verification = step['verification']
        assert 'test_exit_code' not in verification
        assert 'test_output_tail' not in verification
        assert verification.get('test_command') is None


def test_seed_selects_variant_deterministically() -> None:
    scenario = scenario_runtime.get_scenario(SLUG)
    variants = json.loads(scenario['script_json'])['variants']
    assert len(variants) == 2
    # seed % len(variants) is the whole mechanism -- seed=0 always selects
    # variant index 0, and with exactly 2 variants, seed=1 always selects
    # variant index 1.
    run_0 = asyncio.run(scenario_runtime.run_scenario(SLUG, seed=0))
    trace_0 = json.loads(run_0['trace_json'])
    assert trace_0['variant_index'] == 0
    assert trace_0['steps'][0]['title'] == variants[0][0]['title']
    run_1 = asyncio.run(scenario_runtime.run_scenario(SLUG, seed=1))
    trace_1 = json.loads(run_1['trace_json'])
    assert trace_1['variant_index'] == 1
    assert trace_1['steps'][0]['title'] == variants[1][0]['title']


def test_replay_reuses_original_seed_and_selects_same_variant() -> None:
    baseline = asyncio.run(scenario_runtime.run_scenario(SLUG, seed=1))
    replay = asyncio.run(scenario_runtime.replay_scenario(SLUG))
    assert replay['seed'] == baseline['seed'] == 1
    assert json.loads(replay['trace_json'])['variant_index'] == 1
    assert replay['trace_hash'] == baseline['trace_hash']


def test_replay_against_run_missing_seed_raises_valueerror() -> None:
    """Legacy safety net: a completed run from before the seed column
    existed has seed=NULL. Replaying it must fail loudly rather than
    silently generating a fresh, non-reproducing seed."""
    baseline = asyncio.run(scenario_runtime.run_scenario(SLUG))
    with transaction() as conn:
        conn.execute('UPDATE scenario_runs SET seed=NULL WHERE id=?', (baseline['id'],))
    with pytest.raises(ValueError):
        asyncio.run(scenario_runtime.replay_scenario(SLUG, against_run_id=baseline['id']))


def test_replay_with_no_prior_completed_run_raises_valueerror() -> None:
    probe_slug = 'q11-3-piece1-replay-probe-v1'
    with transaction() as conn:
        conn.execute(
            '''INSERT OR IGNORE INTO scenarios(slug,name,version,description,script_json,created_at)
               VALUES(?,?,?,?,?,?)''',
            (probe_slug, 'Replay probe (no runs yet)', 1, 'test-only scenario with zero runs',
             json.dumps([{'title': 'noop', 'instruction': 'This step is never executed by this test.'}]),
             utc_now())
        )
    with pytest.raises(ValueError):
        asyncio.run(scenario_runtime.replay_scenario(probe_slug))


def test_replay_against_latest_completed_run_matches() -> None:
    baseline = asyncio.run(scenario_runtime.run_scenario(SLUG))
    replay = asyncio.run(scenario_runtime.replay_scenario(SLUG))
    assert replay['replay_of_run_id'] == baseline['id']
    assert replay['replay_match'] == 1
    assert replay['trace_hash'] == baseline['trace_hash']


def test_replay_against_explicit_run_id_matches() -> None:
    baseline = asyncio.run(scenario_runtime.run_scenario(SLUG))
    # An unrelated run happens in between -- explicit against_run_id must
    # still compare against the one actually requested, not merely "latest".
    asyncio.run(scenario_runtime.run_scenario(SLUG))
    replay = asyncio.run(scenario_runtime.replay_scenario(SLUG, against_run_id=baseline['id']))
    assert replay['replay_of_run_id'] == baseline['id']
    assert replay['replay_match'] == 1


def test_replay_against_run_id_from_another_scenario_raises_valueerror() -> None:
    probe_slug = 'q11-3-piece1-cross-scenario-probe-v1'
    with transaction() as conn:
        conn.execute(
            '''INSERT OR IGNORE INTO scenarios(slug,name,version,description,script_json,created_at)
               VALUES(?,?,?,?,?,?)''',
            (probe_slug, 'Cross-scenario probe', 1, 'test-only scenario',
             json.dumps([{'title': 'noop', 'instruction': 'Unused content, still runs through Mock.'}]),
             utc_now())
        )
    other_run = asyncio.run(scenario_runtime.run_scenario(probe_slug))
    with pytest.raises(ValueError):
        asyncio.run(scenario_runtime.replay_scenario(SLUG, against_run_id=other_run['id']))


# ---- HTTP layer ----

def test_http_list_scenarios_includes_builtin() -> None:
    response = client.get('/api/scenarios')
    assert response.status_code == 200, response.text
    slugs = {s['slug'] for s in response.json()}
    assert SLUG in slugs


def test_http_get_scenario_detail() -> None:
    response = client.get(f'/api/scenarios/{SLUG}')
    assert response.status_code == 200, response.text
    assert response.json()['slug'] == SLUG


def test_http_get_scenario_detail_unknown_slug_is_404() -> None:
    response = client.get('/api/scenarios/does-not-exist-v1')
    assert response.status_code == 404


def test_http_run_scenario_returns_completed_run() -> None:
    response = client.post(f'/api/scenarios/{SLUG}/run', json=RUN_PAYLOAD)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body['run']['status'] == 'completed'
    assert body['run']['trace_hash']


def test_http_run_unknown_scenario_is_404() -> None:
    response = client.post('/api/scenarios/does-not-exist-v1/run', json=RUN_PAYLOAD)
    assert response.status_code == 404


def test_http_list_scenario_runs_after_running() -> None:
    client.post(f'/api/scenarios/{SLUG}/run', json=RUN_PAYLOAD)
    response = client.get(f'/api/scenarios/{SLUG}/runs')
    assert response.status_code == 200, response.text
    runs = response.json()
    assert len(runs) >= 1
    assert all(r['scenario_id'] for r in runs)


def test_http_replay_scenario_reports_match() -> None:
    client.post(f'/api/scenarios/{SLUG}/run', json=RUN_PAYLOAD)
    response = client.post(f'/api/scenarios/{SLUG}/replay', json=RUN_PAYLOAD)
    assert response.status_code == 200, response.text
    assert response.json()['run']['replay_match'] == 1


def test_http_get_scenario_run_detail_unknown_id_is_404() -> None:
    response = client.get('/api/scenario-runs/999999')
    assert response.status_code == 404


def test_http_get_scenario_run_detail_returns_full_trace() -> None:
    run = client.post(f'/api/scenarios/{SLUG}/run', json=RUN_PAYLOAD).json()
    response = client.get(f"/api/scenario-runs/{run['run']['id']}")
    assert response.status_code == 200, response.text
    assert response.json()['trace_hash'] == run['run']['trace_hash']
