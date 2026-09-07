"""Q11.3 Piece 3: tests for connect_scenariohub.py. Uses httpx.MockTransport
(the same injectable `transport` parameter connect_inmyrnd.py's real
RndAuthorityClient already exposes) rather than pytest-asyncio, so these
run under plain pytest regardless of whether that plugin is configured --
each test wraps its coroutine with asyncio.run() directly.
"""
import asyncio
import hashlib
import json

import httpx
import pytest

from services.api.app.connect_scenariohub import (
    ScenarioAuthorityClient,
    ScenarioExecutionError,
    scenario_digest,
    scenario_digest_from_canonical_json,
    scenario_step_count,
)


def _run(coro):
    return asyncio.run(coro)


AUTH_ID = 'scenauth_' + 'a' * 48
INTENT_ID = 'scenhubi_' + 'b' * 48
HUB_RECEIPT_ID = 'scenhubr_' + 'c' * 48


def _client(handler) -> ScenarioAuthorityClient:
    return ScenarioAuthorityClient(
        base_url='http://127.0.0.1:8787',
        hub_service_token='x' * 32,
        transport=httpx.MockTransport(handler),
    )


class TestScenarioDigest:
    def test_sorted_keys_canonical(self):
        digest = scenario_digest({'b': 1, 'a': 2})
        assert digest.startswith('sha256:')
        assert len(digest) == len('sha256:') + 64

    def test_deterministic_regardless_of_input_key_order(self):
        assert scenario_digest({'b': 1, 'a': 2}) == scenario_digest({'a': 2, 'b': 1})

    def test_non_ascii_is_not_escaped_away(self):
        # ensure_ascii=False means a non-ASCII character changes the digest
        # from its ASCII-escaped equivalent -- catches an accidental
        # ensure_ascii=True regression, the same class of bug Piece 2's
        # discovery flagged for R&D's experiment_digest().
        with_accent = scenario_digest({'title': 'café'})
        without_accent = scenario_digest({'title': 'cafe'})
        assert with_accent != without_accent

    def test_consistent_with_scenario_runtime_own_canonical_json_convention(self):
        # scenario_runtime.py's own _canonical_json() is confirmed to use
        # json.dumps(value, sort_keys=True, separators=(',', ':'),
        # ensure_ascii=False) -- this test fails if scenario_digest() ever
        # silently drifts from that exact convention.
        script = [{'step': 1, 'instruction': 'café recall'}]
        canonical = json.dumps(script, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
        expected = f'sha256:{hashlib.sha256(canonical.encode("utf-8")).hexdigest()}'
        assert scenario_digest(script) == expected

    def test_from_canonical_json_matches_scenario_digest_on_already_sorted_input(self):
        script = [{'a': 1, 'b': 2}]
        canonical = json.dumps(script, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
        assert scenario_digest_from_canonical_json(canonical) == scenario_digest(script)


class TestScenarioStepCount:
    def test_counts_a_json_array(self):
        assert scenario_step_count(json.dumps([1, 2, 3])) == 3

    def test_none_for_missing_value(self):
        assert scenario_step_count(None) is None
        assert scenario_step_count('') is None

    def test_none_for_malformed_json(self):
        assert scenario_step_count('{not json') is None

    def test_none_for_non_array_json(self):
        assert scenario_step_count(json.dumps({'not': 'a list'})) is None


class TestScenarioAuthorityClientRequestShape:
    def test_authorize_sends_confirmed_hub_field_names(self):
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen['body'] = json.loads(request.content)
            return httpx.Response(200, json={'authorizationId': AUTH_ID})

        client = _client(handler)
        digest = scenario_digest([{'step': 1}])
        _run(client.authorize(
            workflow_run_id='inmyai-scenario-run-1', delegation_id='inmyai-scenario-run-1',
            scenario_slug='q11-3-context-recall-v1', scenario_version=1,
            scenario_digest=digest, idempotency_key='idem-test-key-0001',
        ))
        body = seen['body']
        assert set(body.keys()) == {
            'workflowRunId', 'delegationId', 'providerId', 'actionId', 'scenarioSlug',
            'scenarioVersion', 'scenarioDigest', 'idempotencyKey',
        }
        assert body['providerId'] == 'inmyai-scenario'
        assert body['actionId'] == 'scenario.run'

    def test_record_intent_sends_confirmed_hub_field_names(self):
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen['body'] = json.loads(request.content)
            return httpx.Response(200, json={'intentId': INTENT_ID})

        client = _client(handler)
        digest = scenario_digest([{'step': 1}])
        _run(client.record_intent(
            workflow_run_id='wf-run-1', delegation_id='dl-run-1', authorization_id=AUTH_ID,
            idempotency_key='idem-test-key-0001', scenario_slug='q11-3-context-recall-v1',
            scenario_version=1, scenario_digest=digest, started_at='2026-09-04T00:00:00.000Z',
        ))
        assert set(seen['body'].keys()) == {
            'workflowRunId', 'delegationId', 'authorizationId', 'idempotencyKey', 'providerId',
            'actionId', 'scenarioSlug', 'scenarioVersion', 'scenarioDigest', 'startedAt',
        }

    def test_record_execution_sends_confirmed_hub_field_names(self):
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen['body'] = json.loads(request.content)
            return httpx.Response(200, json={'receiptId': HUB_RECEIPT_ID})

        client = _client(handler)
        digest = scenario_digest([{'step': 1}])
        receipt = {
            'schemaVersion': '1.0.0', 'receiptId': 'scenrct_' + 'd' * 64, 'authorizationId': AUTH_ID,
            'providerId': 'inmyai-scenario', 'actionId': 'scenario.run', 'scenarioSlug': 'q11-3-context-recall-v1',
            'scenarioVersion': 1, 'scenarioDigest': digest, 'mode': 'scenario-execution', 'riskClass': 'R1',
            'idempotencyKey': 'idem-test-key-0001', 'executedAt': '2026-09-04T00:00:05.000Z',
            'outcome': 'completed', 'outputs': {'traceHash': 'sha256:' + 'e' * 64, 'stepCount': 3,
                                                 'replayOfTraceHash': None, 'replayMatch': None},
        }
        _run(client.record_execution(
            workflow_run_id='wf-run-1', delegation_id='dl-run-1', authorization_id=AUTH_ID,
            idempotency_key='idem-test-key-0001', scenario_slug='q11-3-context-recall-v1',
            scenario_version=1, scenario_digest=digest, recorded_at='2026-09-04T00:00:06.000Z',
            executor_receipt=receipt,
        ))
        assert set(seen['body'].keys()) == {
            'workflowRunId', 'delegationId', 'authorizationId', 'idempotencyKey', 'providerId',
            'actionId', 'scenarioSlug', 'scenarioVersion', 'scenarioDigest', 'recordedAt', 'executorReceipt',
        }

    def test_record_execution_rejects_invalid_outcome_before_any_http_call(self):
        called = []

        def handler(request: httpx.Request) -> httpx.Response:
            called.append(1)
            return httpx.Response(200, json={})

        client = _client(handler)
        digest = scenario_digest([{'step': 1}])
        bad_receipt = {'receiptId': 'scenrct_' + 'd' * 64, 'outcome': 'timed_out'}
        with pytest.raises(ValueError):
            _run(client.record_execution(
                workflow_run_id='w', delegation_id='d', authorization_id=AUTH_ID,
                idempotency_key='idem-test-key-0001', scenario_slug='q11-3-context-recall-v1',
                scenario_version=1, scenario_digest=digest, recorded_at='2026-09-04T00:00:06.000Z',
                executor_receipt=bad_receipt,
            ))
        assert called == []

    def test_non_2xx_hub_response_maps_to_scenario_execution_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(409, json={'error': 'nope', 'code': 'R1_SCENARIO_AUTHORIZATION_REPLAY_MISMATCH'})

        client = _client(handler)
        with pytest.raises(ScenarioExecutionError) as excinfo:
            _run(client.status())
        assert excinfo.value.status_code == 409
        assert excinfo.value.code == 'R1_SCENARIO_AUTHORIZATION_REPLAY_MISMATCH'

    def test_status_route(self):
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == '/api/scenario-execution/r1/status'
            assert request.method == 'GET'
            return httpx.Response(200, json={'executionEnabled': True})

        client = _client(handler)
        result = _run(client.status())
        assert result['executionEnabled'] is True
