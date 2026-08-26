from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from services.api.app.connect_inmysandbox import (
    InMySandboxRuntimeClient,
    SandboxAuthorityClient,
    SandboxExecutionError,
    canonical_json,
    sha256_digest,
)


TOKEN = 'hub-service-test-token-0123456789'
AUTH_ID = 'sbxauth_' + ('a' * 20)
RECEIPT_ID = 'sbxrct_' + ('b' * 20)
SANDBOX_ID = 'sbx_' + ('c' * 20)
POLICY_DIGEST = f'sha256:{"a" * 64}'
COMMAND_DIGEST = f'sha256:{"b" * 64}'
INPUT_DIGEST = f'sha256:{"c" * 64}'


def make_authority_client(handler, *, base_url: str = 'http://127.0.0.1:8787') -> SandboxAuthorityClient:
    return SandboxAuthorityClient(
        base_url=base_url,
        hub_service_token=TOKEN,
        timeout_seconds=5,
        transport=httpx.MockTransport(handler),
    )


def make_runtime_client(handler, *, base_url: str = 'http://127.0.0.1:17421') -> InMySandboxRuntimeClient:
    return InMySandboxRuntimeClient(
        base_url=base_url,
        timeout_seconds=5,
        transport=httpx.MockTransport(handler),
    )


# --- canonical_json / sha256_digest -----------------------------------

def test_canonical_json_is_stable_across_key_order() -> None:
    a = canonical_json({'b': 1, 'a': 2})
    b = canonical_json({'a': 2, 'b': 1})
    assert a == b == '{"a":2,"b":1}'


def test_sha256_digest_changes_when_a_field_changes() -> None:
    base = sha256_digest({'image': 'node:22-alpine', 'network': 'none'})
    changed = sha256_digest({'image': 'node:22-alpine', 'network': 'bridge'})
    assert base != changed
    assert base.startswith('sha256:') and len(base) == 71


# --- loopback URL validation (both clients) -----------------------------

def test_authority_client_accepts_only_explicit_loopback_http_origins() -> None:
    handler = lambda request: httpx.Response(200, json={'ok': True})
    assert make_authority_client(handler).base_url == 'http://127.0.0.1:8787'
    for invalid in (
        'http://localhost:8787',
        'https://127.0.0.1:8787',
        'http://127.0.0.1',
        'http://user:pass@127.0.0.1:8787',
        'http://127.0.0.1:8787/api',
    ):
        with pytest.raises(ValueError):
            make_authority_client(handler, base_url=invalid)


def test_runtime_client_accepts_only_explicit_loopback_http_origins() -> None:
    handler = lambda request: httpx.Response(200, json={'ok': True})
    assert make_runtime_client(handler).base_url == 'http://127.0.0.1:17421'
    with pytest.raises(ValueError):
        make_runtime_client(handler, base_url='https://127.0.0.1:17421')


def test_runtime_client_never_sends_an_authorization_header() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured['authorization'] = request.headers.get('authorization')
        return httpx.Response(200, json={'ok': True, 'product': 'InMySandbox'})

    async def run() -> dict:
        return await make_runtime_client(handler).health()

    asyncio.run(run())
    assert captured['authorization'] is None


# --- SandboxAuthorityClient: authorize/intent/record forward exact bodies

def test_authorize_forwards_digests_only_never_raw_policy_or_command() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured['path'] = request.url.path
        captured['authorization'] = request.headers.get('authorization')
        captured['body'] = json.loads(request.content)
        return httpx.Response(200, json={'authorized': True, 'authorizationId': AUTH_ID})

    async def run() -> dict:
        return await make_authority_client(handler).authorize(
            workflow_run_id='run_abcdefghijklmnop',
            delegation_id='dlg_abcdefghijklmnop',
            policy_digest=POLICY_DIGEST,
            command_digest=COMMAND_DIGEST,
            idempotency_key='idem_abcdefghijklmnop',
            input_digest=INPUT_DIGEST,
            input_bytes=128,
            input_sensitivity='INTERNAL',
        )

    payload = asyncio.run(run())
    assert payload['authorized'] is True
    assert captured['path'] == '/api/sandbox-execution/r1/authorize'
    assert captured['authorization'] == f'Bearer {TOKEN}'
    assert captured['body'] == {
        'workflowRunId': 'run_abcdefghijklmnop',
        'delegationId': 'dlg_abcdefghijklmnop',
        'providerId': 'inmysandbox',
        'actionId': 'sandbox.run',
        'policyDigest': POLICY_DIGEST,
        'commandDigest': COMMAND_DIGEST,
        'idempotencyKey': 'idem_abcdefghijklmnop',
        'inputDigest': INPUT_DIGEST,
        'inputBytes': 128,
        'inputSensitivity': 'INTERNAL',
    }
    serialized = json.dumps(captured['body'])
    assert 'command' not in serialized.lower().replace('commanddigest', '')
    assert '"policy"' not in serialized


def test_authorize_rejects_input_bytes_above_the_pinned_policy_cap_before_any_request() -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={})

    async def run() -> None:
        await make_authority_client(handler).authorize(
            workflow_run_id='run_abcdefghijklmnop',
            delegation_id='dlg_abcdefghijklmnop',
            policy_digest=POLICY_DIGEST,
            command_digest=COMMAND_DIGEST,
            idempotency_key='idem_abcdefghijklmnop',
            input_digest=INPUT_DIGEST,
            input_bytes=999999,
            input_sensitivity='INTERNAL',
        )

    with pytest.raises(ValueError):
        asyncio.run(run())
    assert calls == []


def test_authorize_rejects_secret_sensitivity_before_any_request() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError('should not be called')

    async def run() -> None:
        await make_authority_client(handler).authorize(
            workflow_run_id='run_abcdefghijklmnop',
            delegation_id='dlg_abcdefghijklmnop',
            policy_digest=POLICY_DIGEST,
            command_digest=COMMAND_DIGEST,
            idempotency_key='idem_abcdefghijklmnop',
            input_digest=INPUT_DIGEST,
            input_bytes=1,
            input_sensitivity='SECRET',
        )

    with pytest.raises(ValueError):
        asyncio.run(run())


def test_record_intent_forwards_exact_body_and_bearer() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured['path'] = request.url.path
        captured['body'] = json.loads(request.content)
        return httpx.Response(200, json={'intentId': 'sbxhubi_x'})

    async def run() -> dict:
        return await make_authority_client(handler).record_intent(
            workflow_run_id='run_abcdefghijklmnop',
            delegation_id='dlg_abcdefghijklmnop',
            authorization_id=AUTH_ID,
            idempotency_key='idem_abcdefghijklmnop',
            policy_digest=POLICY_DIGEST,
            command_digest=COMMAND_DIGEST,
            input_digest=INPUT_DIGEST,
            started_at='2026-08-25T18:00:00.000Z',
        )

    payload = asyncio.run(run())
    assert payload['intentId'] == 'sbxhubi_x'
    assert captured['path'] == '/api/sandbox-execution/r1/intent'
    assert captured['body']['authorizationId'] == AUTH_ID
    assert captured['body']['startedAt'] == '2026-08-25T18:00:00.000Z'


def test_record_execution_validates_outcome_and_receipt_ids_before_any_request() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError('should not be called')

    receipt = {
        'schemaVersion': '1.0.0',
        'receiptId': RECEIPT_ID,
        'authorizationId': AUTH_ID,
        'outcome': 'not-a-real-outcome',
    }

    async def run() -> None:
        await make_authority_client(handler).record_execution(
            workflow_run_id='run_abcdefghijklmnop',
            delegation_id='dlg_abcdefghijklmnop',
            authorization_id=AUTH_ID,
            idempotency_key='idem_abcdefghijklmnop',
            policy_digest=POLICY_DIGEST,
            command_digest=COMMAND_DIGEST,
            input_digest=INPUT_DIGEST,
            recorded_at='2026-08-25T18:00:30.000Z',
            executor_receipt=receipt,
        )

    with pytest.raises(ValueError):
        asyncio.run(run())


def test_record_execution_forwards_receipt_unmodified_on_success() -> None:
    captured: dict = {}
    receipt = {
        'schemaVersion': '1.0.0',
        'receiptId': RECEIPT_ID,
        'authorizationId': AUTH_ID,
        'outcome': 'completed',
        'outputs': {'exitCode': 0, 'timedOut': False, 'durationMs': 120, 'artifactCount': 0, 'artifactBytes': 0},
    }

    def handler(request: httpx.Request) -> httpx.Response:
        captured['body'] = json.loads(request.content)
        return httpx.Response(200, json={'receiptId': 'sbxhubr_x', 'outcome': 'completed'})

    async def run() -> dict:
        return await make_authority_client(handler).record_execution(
            workflow_run_id='run_abcdefghijklmnop',
            delegation_id='dlg_abcdefghijklmnop',
            authorization_id=AUTH_ID,
            idempotency_key='idem_abcdefghijklmnop',
            policy_digest=POLICY_DIGEST,
            command_digest=COMMAND_DIGEST,
            input_digest=INPUT_DIGEST,
            recorded_at='2026-08-25T18:00:30.000Z',
            executor_receipt=receipt,
        )

    payload = asyncio.run(run())
    assert payload['receiptId'] == 'sbxhubr_x'
    assert captured['body']['executorReceipt'] == receipt


# --- Hub-side errors never set execution_may_have_run -------------------

def test_authority_client_errors_never_set_execution_may_have_run() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={'error': 'credential denied', 'code': 'R1_SANDBOX_UNAUTHENTICATED_ACTOR'})

    async def run() -> None:
        await make_authority_client(handler).status()

    with pytest.raises(SandboxExecutionError) as excinfo:
        asyncio.run(run())
    assert excinfo.value.status_code == 401
    assert excinfo.value.code == 'R1_SANDBOX_UNAUTHENTICATED_ACTOR'
    assert excinfo.value.execution_may_have_run is False


# --- InMySandboxRuntimeClient: create/run/stop/destroy ------------------

def test_create_sandbox_failure_response_is_not_flagged_as_ambiguous() -> None:
    # A clean non-2xx response (InMySandbox's own handler ran and reported
    # failure, e.g. no engine available) is a DEFINITIVE "it did not
    # happen" signal, same as ConnectOpenRouterClient's committed model --
    # not the ambiguous case. No container was created; safe to retry
    # under the same idempotency key.
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={'error': 'sandbox engine unavailable'})

    async def run() -> None:
        await make_runtime_client(handler).create_sandbox({'image': 'node:22-alpine', 'network': 'none'})

    with pytest.raises(SandboxExecutionError) as excinfo:
        asyncio.run(run())
    assert excinfo.value.execution_may_have_run is False


def test_create_sandbox_flags_execution_may_have_run_when_a_2xx_response_body_is_truncated() -> None:
    # The genuinely ambiguous case: InMySandbox answered 201 (it believes
    # creation succeeded) but the body we received is not valid JSON --
    # e.g. the connection dropped mid-response. We cannot tell whether the
    # container now exists, so this must be flagged.
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(201, content=b'{"id": "sbx_truncated', headers={'content-type': 'application/json'})

    async def run() -> None:
        await make_runtime_client(handler).create_sandbox({'image': 'node:22-alpine', 'network': 'none'})

    with pytest.raises(SandboxExecutionError) as excinfo:
        asyncio.run(run())
    assert excinfo.value.execution_may_have_run is True


def test_create_sandbox_forwards_exact_policy_body() -> None:
    captured: dict = {}
    policy = {'image': 'node:22-alpine', 'network': 'none', 'memoryMb': 512, 'cpus': 1, 'diskMb': 256, 'ttlSeconds': 600, 'pids': 64}

    def handler(request: httpx.Request) -> httpx.Response:
        captured['path'] = request.url.path
        captured['body'] = json.loads(request.content)
        return httpx.Response(201, json={'id': SANDBOX_ID, 'status': 'READY'})

    async def run() -> dict:
        return await make_runtime_client(handler).create_sandbox(policy)

    payload = asyncio.run(run())
    assert payload['id'] == SANDBOX_ID
    assert captured['path'] == '/api/sandboxes'
    assert captured['body'] == {'policy': policy}


def test_run_forwards_command_inputs_and_timeout_and_rejects_out_of_range_timeout() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured['path'] = request.url.path
        captured['body'] = json.loads(request.content)
        return httpx.Response(201, json={'id': 'job_x', 'status': 'FINISHED', 'exitCode': 0, 'stdout': 'hi', 'stderr': '', 'timedOut': False, 'durationMs': 42, 'artifacts': []})

    async def run() -> dict:
        return await make_runtime_client(handler).run(
            sandbox_id=SANDBOX_ID, command=['node', '--version'], inputs=[], timeout_ms=30000,
        )

    payload = asyncio.run(run())
    assert payload['status'] == 'FINISHED'
    assert captured['path'] == f'/api/sandboxes/{SANDBOX_ID}/run'
    assert captured['body'] == {'command': ['node', '--version'], 'inputs': [], 'timeoutMs': 30000}

    def handler2(request: httpx.Request) -> httpx.Response:
        raise AssertionError('should not be called')

    async def run_bad_timeout() -> None:
        await make_runtime_client(handler2).run(sandbox_id=SANDBOX_ID, command=['ls'], timeout_ms=1_000_000)

    with pytest.raises(ValueError):
        asyncio.run(run_bad_timeout())


def test_run_rejects_empty_command_before_any_request() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError('should not be called')

    async def run() -> None:
        await make_runtime_client(handler).run(sandbox_id=SANDBOX_ID, command=[])

    with pytest.raises(ValueError):
        asyncio.run(run())


def test_stop_and_destroy_never_flag_execution_may_have_run_even_on_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={'error': 'sandbox not found'})

    async def run_stop() -> None:
        await make_runtime_client(handler).stop(SANDBOX_ID)

    async def run_destroy() -> None:
        await make_runtime_client(handler).destroy(SANDBOX_ID)

    with pytest.raises(SandboxExecutionError) as stop_exc:
        asyncio.run(run_stop())
    assert stop_exc.value.execution_may_have_run is False

    with pytest.raises(SandboxExecutionError) as destroy_exc:
        asyncio.run(run_destroy())
    assert destroy_exc.value.execution_may_have_run is False


def test_destroy_uses_delete_method_against_the_bare_sandbox_path() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured['method'] = request.method
        captured['path'] = request.url.path
        return httpx.Response(200, json={'ok': True})

    async def run() -> dict:
        return await make_runtime_client(handler).destroy(SANDBOX_ID)

    payload = asyncio.run(run())
    assert payload == {'ok': True}
    assert captured == {'method': 'DELETE', 'path': f'/api/sandboxes/{SANDBOX_ID}'}


def test_invalid_sandbox_id_is_rejected_before_any_request() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError('should not be called')

    async def run() -> None:
        await make_runtime_client(handler).run(sandbox_id='not-a-real-id', command=['ls'])

    with pytest.raises(ValueError):
        asyncio.run(run())


# --- source hygiene -------------------------------------------------------

def test_connect_inmysandbox_source_never_hardcodes_a_provider_secret_or_real_provider_endpoint() -> None:
    # Design-lineage comments legitimately name "OpenRouter" and
    # connect_openrouter.py (this module's precedent) -- that is prose, not
    # a leak. What must never appear is a real provider credential name,
    # domain, or key material, none of which this module has any reason to
    # reference at all (InMySandbox holds no third-party secret).
    from pathlib import Path
    source = Path('services/api/app/connect_inmysandbox.py').read_text(encoding='utf-8')
    assert 'openrouter.ai' not in source.lower()
    assert 'api.openai.com' not in source.lower()
    assert 'OPENROUTER_API_KEY' not in source
    assert 'api_key' not in source.lower()
    assert 'access_token' not in source.lower()
