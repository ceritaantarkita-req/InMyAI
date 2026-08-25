from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest

from services.api.app.connect_openrouter import ConnectOpenRouterClient, ConnectOpenRouterError


TOKEN = 'hub-service-test-token-0123456789'
CONNECTION_ID = 'conn_' + ('a' * 16)


def make_client(handler, *, base_url: str = 'http://127.0.0.1:8766') -> ConnectOpenRouterClient:
    return ConnectOpenRouterClient(
        base_url=base_url,
        hub_service_token=TOKEN,
        timeout_seconds=5,
        transport=httpx.MockTransport(handler),
    )


def test_connect_client_accepts_only_explicit_loopback_http_origins() -> None:
    handler = lambda request: httpx.Response(200, json={'ok': True})
    assert make_client(handler).base_url == 'http://127.0.0.1:8766'
    assert make_client(handler, base_url='http://[::1]:8766').base_url == 'http://[::1]:8766'
    for invalid in (
        'http://localhost:8766',
        'http://192.168.1.20:8766',
        'https://127.0.0.1:8766',
        'http://127.0.0.1',
        'http://user:pass@127.0.0.1:8766',
        'http://127.0.0.1:8766/api',
        'http://127.0.0.1:8766/?x=1',
    ):
        with pytest.raises(ValueError):
            make_client(handler, base_url=invalid)


def test_status_uses_exact_local_bridge_route_and_hub_service_bearer() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured['method'] = request.method
        captured['url'] = str(request.url)
        captured['authorization'] = request.headers.get('authorization')
        return httpx.Response(200, json={'provider': 'openrouter', 'ready': True})

    async def run() -> dict:
        return await make_client(handler).status()

    payload = asyncio.run(run())
    assert payload == {'provider': 'openrouter', 'ready': True}
    assert captured == {
        'method': 'GET',
        'url': 'http://127.0.0.1:8766/api/openrouter/status',
        'authorization': f'Bearer {TOKEN}',
    }


def test_model_discovery_forwards_only_opaque_connection_and_idempotency() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured['path'] = request.url.path
        captured['body'] = json.loads(request.content)
        return httpx.Response(200, json={'models': [{'id': 'qwen/qwen3-coder'}]})

    async def run() -> dict:
        return await make_client(handler).list_models(
            connection_id=CONNECTION_ID,
            idempotency_key='openrouter-models-test-0001',
        )

    payload = asyncio.run(run())
    assert payload['models'][0]['id'] == 'qwen/qwen3-coder'
    assert captured['path'] == '/api/openrouter/models'
    assert captured['body'] == {
        'connectionId': CONNECTION_ID,
        'idempotencyKey': 'openrouter-models-test-0001',
    }
    serialized = json.dumps(captured['body']).lower()
    assert 'api_key' not in serialized
    assert 'access_token' not in serialized


def test_chat_forwards_explicit_model_and_bounded_governance_metadata() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured['path'] = request.url.path
        captured['body'] = json.loads(request.content)
        return httpx.Response(200, json={
            'authorized': True,
            'receipt': {
                'outputs': {
                    'message': {'role': 'assistant', 'content': 'Hello from OpenRouter.'},
                    'returnedModel': 'qwen/qwen3-coder',
                },
            },
        })

    async def run() -> dict:
        return await make_client(handler).chat(
            workflow_run_id='chat-workflow-0001',
            delegation_id='inmyai-chat-0001',
            connection_id=CONNECTION_ID,
            model_id='qwen/qwen3-coder',
            idempotency_key='openrouter-chat-test-0001',
            input_sensitivity='INTERNAL',
            requested_output_tokens=512,
            messages=[
                {'role': 'system', 'content': 'Use project context.'},
                {'role': 'user', 'content': 'Say hello.'},
            ],
        )

    payload = asyncio.run(run())
    assert payload['authorized'] is True
    assert captured['path'] == '/api/openrouter/chat'
    assert captured['body'] == {
        'workflowRunId': 'chat-workflow-0001',
        'delegationId': 'inmyai-chat-0001',
        'connectionId': CONNECTION_ID,
        'modelId': 'qwen/qwen3-coder',
        'idempotencyKey': 'openrouter-chat-test-0001',
        'inputSensitivity': 'INTERNAL',
        'requestedOutputTokens': 512,
        'inputs': {
            'messages': [
                {'role': 'system', 'content': 'Use project context.'},
                {'role': 'user', 'content': 'Say hello.'},
            ],
        },
    }


def test_http_and_network_errors_are_sanitized_without_token_or_body_leakage() -> None:
    async def http_failure() -> None:
        client = make_client(lambda request: httpx.Response(502, json={
            'code': 'CONNECT_UPSTREAM_FAILED',
            'detail': f'secret body {TOKEN}',
        }))
        with pytest.raises(ConnectOpenRouterError) as raised:
            await client.status()
        message = str(raised.value)
        assert '502' in message
        assert 'CONNECT_UPSTREAM_FAILED' in message
        assert 'secret body' not in message
        assert TOKEN not in message

    def network_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f'socket secret {TOKEN}', request=request)

    async def network_failure() -> None:
        client = make_client(network_handler)
        with pytest.raises(ConnectOpenRouterError) as raised:
            await client.status()
        assert str(raised.value) == 'InMyConnect local runtime is unavailable.'
        assert TOKEN not in str(raised.value)

    asyncio.run(http_failure())
    asyncio.run(network_failure())


def test_client_rejects_invalid_model_connection_and_sensitivity_before_network() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={})

    client = make_client(handler)

    async def run() -> None:
        with pytest.raises(ValueError):
            await client.list_models(connection_id='not-a-connection', idempotency_key='valid-idem-0001')
        with pytest.raises(ValueError):
            await client.chat(
                workflow_run_id='workflow-001',
                delegation_id='delegation-001',
                connection_id=CONNECTION_ID,
                model_id='bad model',
                idempotency_key='valid-idem-0002',
                input_sensitivity='INTERNAL',
                requested_output_tokens=512,
                messages=[{'role': 'user', 'content': 'hello'}],
            )
        with pytest.raises(ValueError):
            await client.chat(
                workflow_run_id='workflow-001',
                delegation_id='delegation-001',
                connection_id=CONNECTION_ID,
                model_id='qwen/qwen3-coder',
                idempotency_key='valid-idem-0003',
                input_sensitivity='SENSITIVE',
                requested_output_tokens=512,
                messages=[{'role': 'user', 'content': 'hello'}],
            )

    asyncio.run(run())
    assert calls == 0


def test_connect_client_source_has_no_provider_endpoint_or_provider_credential_lookup() -> None:
    source = Path('services/api/app/connect_openrouter.py').read_text(encoding='utf-8')
    lowered = source.lower()
    for forbidden in (
        'openrouter.ai',
        'api.openai.com',
        'openrouter_api_key',
        'openai_api_key',
        'os.environ',
        'getenv(',
        'subprocess',
        'models: [',
        'fallbacks: [',
    ):
        assert forbidden not in lowered, forbidden
    assert '/api/openrouter/models' in source
    assert '/api/openrouter/chat' in source
    assert 'follow_redirects=False' in source


# --------------------------------------------------------------------------
# Q10.8 slice 3 -- streaming client (POST /api/openrouter/chat/stream)
# --------------------------------------------------------------------------


CHAT_ARGS = {
    'workflow_run_id': 'workflow-stream-001',
    'delegation_id': 'delegation-stream-001',
    'connection_id': CONNECTION_ID,
    'model_id': 'qwen/qwen3-coder',
    'idempotency_key': 'openrouter-stream-0001',
    'input_sensitivity': 'INTERNAL',
    'requested_output_tokens': 512,
    'messages': [{'role': 'user', 'content': 'hello'}],
}

RECEIPT = {
    'authorized': True,
    'receipt': {
        'receiptId': 'rcp_stream_0001',
        'outcome': 'completed',
        'outputs': {
            'message': {'role': 'assistant', 'content': 'Hello.'},
            'returnedModel': 'qwen/qwen3-coder',
            'usage': {'totalTokens': 12, 'cost': 0.00042},
        },
    },
}


def sse(*blocks: str) -> str:
    return ''.join(blocks)


def event(name: str, payload: dict) -> str:
    # ensure_ascii=False on purpose: the bridge is Node, and JSON.stringify
    # does NOT escape non-ASCII, so real multi-byte UTF-8 sits on the wire.
    # Python's default (ensure_ascii=True) would quietly make every fixture
    # pure ASCII and hide an entire class of decoding defect.
    return f'event: {name}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n'


def stream_handler(body: str, *, status: int = 200, content_type: str = 'text/event-stream',
                   piece_size: int | None = None, captured: dict | None = None):
    """MockTransport handler that serves `body` as a real byte stream.

    piece_size exists so a test can prove that identical valid SSE is parsed
    the same way no matter how the socket happens to chunk it.
    """
    raw = body.encode('utf-8')
    size = piece_size or max(1, len(raw))

    def handler(request: httpx.Request) -> httpx.Response:
        if captured is not None:
            captured['path'] = request.url.path
            captured['headers'] = dict(request.headers)
            captured['body'] = json.loads(request.content) if request.content else None

        async def parts():
            for start in range(0, len(raw), size):
                yield raw[start:start + size]

        return httpx.Response(status, headers={'content-type': content_type}, content=parts())

    return handler


def run_stream(handler, **overrides) -> dict:
    args = {**CHAT_ARGS, **overrides}

    async def go() -> dict:
        return await make_client(handler).chat_stream(**args)

    return asyncio.run(go())


def test_chat_stream_delivers_deltas_in_order_and_returns_the_governed_receipt() -> None:
    captured: dict = {}
    body = sse(
        event('chunk', {'text': 'Hel'}),
        event('chunk', {'text': 'lo.'}),
        event('done', RECEIPT),
    )
    seen: list[str] = []

    async def go() -> dict:
        return await make_client(stream_handler(body, captured=captured)).chat_stream(
            **CHAT_ARGS, on_chunk=seen.append
        )

    result = asyncio.run(go())
    assert seen == ['Hel', 'lo.']
    assert result == RECEIPT
    assert captured['path'] == '/api/openrouter/chat/stream'
    assert captured['headers']['accept'] == 'text/event-stream'
    assert captured['headers']['authorization'] == f'Bearer {TOKEN}'


def test_chat_stream_sends_byte_identical_governance_metadata_to_the_buffered_path() -> None:
    """The Hub authorizes against exactly these fields.

    If the two paths could drift into shaping the request differently, a
    streamed call could be authorized for something other than what it runs.
    """
    buffered: dict = {}
    streamed: dict = {}

    def buffered_handler(request: httpx.Request) -> httpx.Response:
        buffered['body'] = json.loads(request.content)
        return httpx.Response(200, json=RECEIPT)

    async def go() -> None:
        await make_client(buffered_handler).chat(**CHAT_ARGS)

    asyncio.run(go())
    run_stream(stream_handler(event('done', RECEIPT), captured=streamed))
    assert streamed['body'] == buffered['body']


def test_chat_stream_returns_a_partial_receipt_instead_of_raising() -> None:
    """A stream that breaks after real tokens is spend that was incurred.

    InMyConnect records it as outcome 'partial' and returns it; this client
    must hand that receipt back rather than raising, or the spend is lost at
    the last hop.
    """
    partial = {
        'authorized': True,
        'receipt': {'receiptId': 'rcp_partial', 'outcome': 'partial', 'outputs': {
            'message': {'role': 'assistant', 'content': 'Hel'},
            'usage': None,
        }},
    }
    body = sse(event('chunk', {'text': 'Hel'}), event('done', partial))
    result = run_stream(stream_handler(body))
    assert result['receipt']['outcome'] == 'partial'


def test_chat_stream_never_forwards_raw_upstream_text_from_a_mid_stream_error() -> None:
    secret = 'sk-or-v1-DEADBEEFdeadbeef0123456789'
    body = sse(
        event('chunk', {'text': 'Hel'}),
        event('error', {
            'code': 'R1_PROVIDER_TRANSPORT_FAILED',
            'message': f'upstream said: bad key {secret} for {CONNECTION_ID}',
        }),
    )
    with pytest.raises(ConnectOpenRouterError) as excinfo:
        run_stream(stream_handler(body))
    rendered = f'{excinfo.value} {excinfo.value.code}'
    assert secret not in rendered
    assert CONNECTION_ID not in rendered
    assert 'upstream said' not in rendered
    assert excinfo.value.code == 'R1_PROVIDER_TRANSPORT_FAILED'


def test_chat_stream_error_event_with_an_unsafe_code_is_replaced_not_forwarded() -> None:
    body = sse(event('error', {'code': 'sk-or-v1-leaked-through-the-code-field'}))
    with pytest.raises(ConnectOpenRouterError) as excinfo:
        run_stream(stream_handler(body))
    assert excinfo.value.code == 'CONNECT_STREAM_FAILED'
    assert 'sk-or' not in f'{excinfo.value} {excinfo.value.code}'


def test_chat_stream_failure_before_the_stream_opens_is_an_ordinary_http_error() -> None:
    """Nothing ran, so there is no receipt and no spend -- a real status."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={'code': 'HUB_R1_DENIED', 'message': 'denied'})

    with pytest.raises(ConnectOpenRouterError) as excinfo:
        run_stream(handler)
    assert excinfo.value.status_code == 403
    assert excinfo.value.code == 'HUB_R1_DENIED'


def test_chat_stream_that_ends_without_a_terminal_event_is_reported_as_incomplete() -> None:
    """Distinct from 'nothing happened' on purpose.

    A receipt may exist on the Connect side that never reached this client.
    A caller that treats this as a clean failure and retries under a NEW
    idempotency key pays twice, so the code is its own value.
    """
    body = sse(event('chunk', {'text': 'Hel'}), event('chunk', {'text': 'lo.'}))
    with pytest.raises(ConnectOpenRouterError) as excinfo:
        run_stream(stream_handler(body))
    assert excinfo.value.code == 'CONNECT_STREAM_INCOMPLETE'


def test_chat_stream_skips_keep_alive_comments_and_joins_multi_line_data() -> None:
    """OpenRouter's documented stream interleaves ': OPENROUTER PROCESSING'.

    InMyConnect may pass such comment lines through. They carry no data and
    must never be mistaken for assistant text. A single event's data may
    also legally span several `data:` lines, joined with newlines -- which
    is still valid JSON, since JSON ignores whitespace between tokens.
    """
    body = (
        ': OPENROUTER PROCESSING\n\n'
        + 'event: chunk\ndata: {"text":\ndata: "Hello."}\n\n'
        + ': OPENROUTER PROCESSING\n\n'
        + event('done', RECEIPT)
    )
    seen: list[str] = []

    async def go() -> dict:
        return await make_client(stream_handler(body)).chat_stream(**CHAT_ARGS, on_chunk=seen.append)

    result = asyncio.run(go())
    assert seen == ['Hello.']
    assert result == RECEIPT


def test_identical_sse_parses_the_same_however_the_socket_chunks_it() -> None:
    body = sse(
        ': OPENROUTER PROCESSING\n\n',
        event('chunk', {'text': 'Hel'}),
        event('chunk', {'text': 'lo.'}),
        event('done', RECEIPT),
    )
    outcomes = []
    for piece in (1, 3, 17, len(body)):
        seen: list[str] = []

        async def go(piece=piece, seen=seen) -> dict:
            return await make_client(stream_handler(body, piece_size=piece)).chat_stream(
                **CHAT_ARGS, on_chunk=seen.append
            )

        outcomes.append((asyncio.run(go()), ''.join(seen)))
    assert outcomes == [(RECEIPT, 'Hello.')] * 4


def test_a_throwing_on_chunk_consumer_never_loses_an_already_billed_receipt() -> None:
    body = sse(event('chunk', {'text': 'Hel'}), event('done', RECEIPT))

    def explode(_text: str) -> None:
        raise RuntimeError('rendering blew up')

    async def go() -> dict:
        return await make_client(stream_handler(body)).chat_stream(**CHAT_ARGS, on_chunk=explode)

    assert asyncio.run(go()) == RECEIPT


def test_chat_stream_is_bounded_by_total_bytes() -> None:
    filler = event('chunk', {'text': 'x' * 8192})
    body = filler * 300  # ~2.4 MB, no terminal event
    with pytest.raises(ConnectOpenRouterError) as excinfo:
        run_stream(stream_handler(body, piece_size=64 * 1024))
    assert excinfo.value.code == 'CONNECT_STREAM_TOO_LARGE'


def test_chat_stream_rejects_a_delimiterless_oversized_frame() -> None:
    body = 'event: chunk\ndata: ' + ('x' * (300 * 1024))  # never terminated
    with pytest.raises(ConnectOpenRouterError) as excinfo:
        run_stream(stream_handler(body, piece_size=32 * 1024))
    assert excinfo.value.code == 'CONNECT_STREAM_TOO_LARGE'


def test_chat_stream_rejects_a_response_that_is_not_an_event_stream() -> None:
    with pytest.raises(ConnectOpenRouterError) as excinfo:
        run_stream(stream_handler(json.dumps(RECEIPT), content_type='application/json'))
    assert excinfo.value.code == 'CONNECT_STREAM_INVALID'


def test_chat_stream_rejects_a_malformed_event_payload() -> None:
    body = 'event: done\ndata: {not json\n\n'
    with pytest.raises(ConnectOpenRouterError) as excinfo:
        run_stream(stream_handler(body))
    assert excinfo.value.code == 'CONNECT_STREAM_INVALID'


def test_chat_stream_validates_everything_before_any_network_call() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, headers={'content-type': 'text/event-stream'}, content=b'')

    async def go() -> None:
        client = make_client(handler)
        with pytest.raises(ValueError):
            await client.chat_stream(**{**CHAT_ARGS, 'model_id': 'bad model'})
        with pytest.raises(ValueError):
            await client.chat_stream(**{**CHAT_ARGS, 'input_sensitivity': 'SENSITIVE'})
        with pytest.raises(ValueError):
            await client.chat_stream(**{**CHAT_ARGS, 'connection_id': 'conn_short'})
        with pytest.raises(ValueError):
            await client.chat_stream(**CHAT_ARGS, on_chunk='not callable')

    asyncio.run(go())
    assert calls == 0


def test_stream_route_is_pinned_and_no_provider_endpoint_leaks_into_the_client() -> None:
    source = Path('services/api/app/connect_openrouter.py').read_text(encoding='utf-8')
    assert '/api/openrouter/chat/stream' in source
    assert 'text/event-stream' in source
    lowered = source.lower()
    for forbidden in ('openrouter.ai', 'api.openai.com', 'os.environ', 'getenv('):
        assert forbidden not in lowered, forbidden


# --------------------------------------------------------------------------
# Round 1 adversarial review -- regression locks
# --------------------------------------------------------------------------

from services.api.app import connect_openrouter as _mod  # noqa: E402


def test_multibyte_text_split_across_read_boundaries_never_kills_a_paid_stream() -> None:
    """Round 1, blocking 1.

    Non-ASCII assistant text is ordinary, not exotic: Node's JSON.stringify
    does not escape it, so real multi-byte UTF-8 is on the wire. A socket
    read boundary landing inside one of those characters must not abort a
    generation OpenRouter has already billed.
    """
    text = 'Halo — kabar baik 🎉 ya, café.'
    body = sse(event('chunk', {'text': text}), event('done', RECEIPT))
    seen: list[str] = []

    async def go() -> dict:
        return await make_client(stream_handler(body, piece_size=1)).chat_stream(
            **CHAT_ARGS, on_chunk=seen.append
        )

    assert asyncio.run(go()) == RECEIPT
    assert ''.join(seen) == text


def test_a_terminal_event_beats_the_wall_clock_bound(monkeypatch) -> None:
    """Round 1, blocking 2.

    The receipt was already produced and the spend already incurred. A
    deadline that fires on the very read carrying it would discard money.
    """
    monkeypatch.setattr(_mod, '_MAX_STREAM_DURATION_SECONDS', 0.0)
    body = sse(event('chunk', {'text': 'Hi'}), event('done', RECEIPT))
    assert run_stream(stream_handler(body)) == RECEIPT


def test_a_terminal_event_beats_the_total_byte_bound(monkeypatch) -> None:
    """Round 1, blocking 2 (same defect, size bound)."""
    monkeypatch.setattr(_mod, '_MAX_STREAM_RESPONSE_BYTES', 128)
    body = sse(event('chunk', {'text': 'x' * 4096}), event('done', RECEIPT))
    assert run_stream(stream_handler(body)) == RECEIPT


def test_the_byte_bound_still_stops_a_stream_that_never_terminates(monkeypatch) -> None:
    """The counterpart to the two tests above: relaxing the ordering must
    not have relaxed the bound itself."""
    monkeypatch.setattr(_mod, '_MAX_STREAM_RESPONSE_BYTES', 4096)
    body = event('chunk', {'text': 'x' * 1024}) * 50
    with pytest.raises(ConnectOpenRouterError) as excinfo:
        run_stream(stream_handler(body, piece_size=1024))
    assert excinfo.value.code == 'CONNECT_STREAM_TOO_LARGE'


def test_a_read_boundary_inside_a_crlf_does_not_split_the_terminal_event() -> None:
    """Round 1, should-fix 5.

    Rewriting a trailing lone CR to LF manufactures a blank line -- an SSE
    event delimiter -- inside an event, silently halving the `done` block.
    """
    crlf = (
        'event: chunk\r\ndata: {"text": "Hi"}\r\n\r\n'
        + f'event: done\r\ndata: {json.dumps(RECEIPT, ensure_ascii=False)}\r\n\r\n'
    )
    for piece in (1, 2, 3, 7, len(crlf)):
        assert run_stream(stream_handler(crlf, piece_size=piece)) == RECEIPT


def test_a_terminal_done_without_a_governed_outcome_is_not_reported_as_success() -> None:
    """Round 1, should-fix 6.

    "Returning means a receipt exists" is checked, not assumed.
    """
    for bad in ({}, {'receipt': None}, {'authorized': 'yes'}, {'authorized': True}):
        with pytest.raises(ConnectOpenRouterError) as excinfo:
            run_stream(stream_handler(event('done', bad)))
        assert excinfo.value.code == 'CONNECT_STREAM_INVALID'
        assert excinfo.value.receipt_may_exist is True


def test_a_hub_denial_delivered_as_a_terminal_event_is_still_passed_through() -> None:
    """authorized: false is a governed outcome, not a malformed event."""
    denied = {'authorized': False, 'reason': 'BUDGET_EXCEEDED'}
    assert run_stream(stream_handler(event('done', denied))) == denied


def test_every_failure_after_http_200_is_marked_receipt_may_exist() -> None:
    """Round 1, blocking 3.

    Past 200 the bridge may already have run and recorded a real execution.
    A caller that retries such a call under a NEW idempotency key pays
    twice, so the flag must be set on every post-commit branch -- not only
    on the one that happens to be named 'incomplete'.
    """
    post_commit = [
        ('incomplete', sse(event('chunk', {'text': 'Hi'}))),
        ('malformed', sse(event('chunk', {'text': 'Hi'}), 'event: done\ndata: {nope\n\n')),
        ('bad terminal', sse(event('chunk', {'text': 'Hi'}), event('done', {}))),
        ('error after deltas', sse(event('chunk', {'text': 'Hi'}), event('error', {'code': 'R1_X'}))),
    ]
    for label, body in post_commit:
        with pytest.raises(ConnectOpenRouterError) as excinfo:
            run_stream(stream_handler(body))
        assert excinfo.value.receipt_may_exist is True, label

    # Pre-commit failures are the opposite: nothing ran, so retrying under a
    # fresh key is safe and the flag must stay false.
    def denied(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={'code': 'HUB_R1_DENIED'})

    with pytest.raises(ConnectOpenRouterError) as excinfo:
        run_stream(denied)
    assert excinfo.value.receipt_may_exist is False

    # Round 2: an error event with no prior delta is ALSO marked. It was
    # briefly inferred from "did this client see text?", which is narrower
    # than the thing it describes -- InMyConnect bills on reasoning tokens,
    # tool-call deltas, and usage frames this client never sees, and would
    # record a receipt for them. "I saw no text" is not "no money moved".
    with pytest.raises(ConnectOpenRouterError) as excinfo:
        run_stream(stream_handler(event('error', {'code': 'R1_PROVIDER_TRANSPORT_FAILED'})))
    assert excinfo.value.receipt_may_exist is True


def test_an_oversized_frame_is_rejected_however_the_socket_chunks_it() -> None:
    """Round 1, should-fix 4.

    The guard previously measured only the undrained remainder, so one
    oversized event passed when its delimiter arrived in the same read and
    failed when it did not.
    """
    body = event('chunk', {'text': 'x' * (300 * 1024)})
    for piece in (32 * 1024, len(body)):
        with pytest.raises(ConnectOpenRouterError) as excinfo:
            run_stream(stream_handler(body, piece_size=piece))
        assert excinfo.value.code == 'CONNECT_STREAM_TOO_LARGE'


def test_an_async_on_chunk_is_rejected_rather_than_silently_discarded() -> None:
    """Round 1, nit 7: an un-awaited coroutine yields a perfect receipt and
    zero deltas -- a silent hole, so it fails loudly instead."""

    async def consumer(_text: str) -> None:  # pragma: no cover - never called
        raise AssertionError('must not be invoked')

    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, headers={'content-type': 'text/event-stream'}, content=b'')

    async def go() -> None:
        with pytest.raises(ValueError):
            await make_client(handler).chat_stream(**CHAT_ARGS, on_chunk=consumer)

    asyncio.run(go())
    assert calls == 0


def test_stream_idle_timeout_is_separate_from_the_request_timeout_and_bounded() -> None:
    """Round 1, nit 9: time-to-first-token on a large model can exceed a
    timeout sized for a buffered request, and tripping it destroys a billed
    generation -- so the idle bound is its own knob."""
    handler = lambda request: httpx.Response(200, json={'ok': True})
    assert make_client(handler).stream_idle_timeout_seconds == 60.0
    for invalid in (0, 4, 301, True, 'thirty'):
        with pytest.raises(ValueError):
            ConnectOpenRouterClient(
                base_url='http://127.0.0.1:8766',
                hub_service_token=TOKEN,
                stream_idle_timeout_seconds=invalid,
                transport=httpx.MockTransport(handler),
            )


# --------------------------------------------------------------------------
# Round 2 adversarial review -- regression locks
# --------------------------------------------------------------------------


def test_an_unexpected_exception_after_http_200_is_still_marked_receipt_may_exist() -> None:
    """Round 2, should-fix 2.

    The post-commit handler used to catch three httpx types by name, so a
    decoding error or a RecursionError from json escaped raw -- leaving a
    caller doing `except ConnectOpenRouterError: branch on receipt_may_exist`
    with an exception that has no such attribute, after the bridge committed.
    """

    def exploding(request: httpx.Request) -> httpx.Response:
        async def parts():
            yield b'event: chunk\ndata: {"text": "Hi"}\n\n'
            raise ZeroDivisionError('something nobody predicted')

        return httpx.Response(200, headers={'content-type': 'text/event-stream'}, content=parts())

    with pytest.raises(ConnectOpenRouterError) as excinfo:
        run_stream(exploding)
    assert excinfo.value.receipt_may_exist is True

    # Deeply nested JSON inside a within-bounds frame raises RecursionError
    # from json.loads, which is not a JSONDecodeError.
    deep = 'event: done\ndata: ' + ('[' * 20000) + '\n\n'
    with pytest.raises(ConnectOpenRouterError) as excinfo:
        run_stream(stream_handler(deep))
    assert excinfo.value.receipt_may_exist is True


def test_a_stream_whose_last_byte_is_a_bare_cr_still_yields_its_receipt() -> None:
    """Round 2, should-fix 3 -- a hole opened by round 1's own fix.

    The trailing-CR hold-back had no end-of-stream flush, so a CR-framed
    stream lost a terminal event that was fully on the wire and already
    decoded. Every framing at every chunk size must behave identically.
    """
    for terminator in ('\r\n', '\r', '\n'):
        body = (
            f'event: chunk{terminator}data: {{"text": "Hi"}}{terminator}{terminator}'
            + f'event: done{terminator}data: {json.dumps(RECEIPT, ensure_ascii=False)}{terminator}{terminator}'
        )
        for piece in (1, 2, 3, 5, 13, len(body)):
            assert run_stream(stream_handler(body, piece_size=piece)) == RECEIPT, (terminator, piece)


def test_the_frame_bound_is_enforced_in_bytes_not_characters() -> None:
    """Round 2, should-fix 5.

    len() counts characters, and this stream carries unescaped multi-byte
    UTF-8 from a Node bridge, so a character check allowed up to 4x the
    declared byte bound.
    """
    wide = '\U0001f600' * 200_000  # 200k chars, 800 KB on the wire
    body = event('chunk', {'text': wide})
    assert len(body) < 4 * _mod._MAX_SSE_EVENT_BYTES
    assert len(body.encode('utf-8')) > _mod._MAX_SSE_EVENT_BYTES
    with pytest.raises(ConnectOpenRouterError) as excinfo:
        run_stream(stream_handler(body, piece_size=64 * 1024))
    assert excinfo.value.code == 'CONNECT_STREAM_TOO_LARGE'


def test_an_object_with_an_async_call_is_rejected_up_front() -> None:
    """Round 2, should-fix 4: iscoroutinefunction misses this shape."""

    class Consumer:
        async def __call__(self, text: str) -> None:  # pragma: no cover
            raise AssertionError('must not be invoked')

    async def go() -> None:
        with pytest.raises(ValueError):
            await make_client(stream_handler('')).chat_stream(**CHAT_ARGS, on_chunk=Consumer())

    asyncio.run(go())


def test_a_sync_wrapper_returning_a_coroutine_warns_and_keeps_the_receipt() -> None:
    """Round 2, should-fix 4 (the shape that cannot be caught up front).

    Detected only when it is called, and by then a generation is already
    being paid for -- so it warns loudly and returns the receipt rather than
    raising and losing it.
    """

    async def real_consumer(text: str) -> None:  # pragma: no cover
        raise AssertionError('must not be awaited')

    def wrapper(text: str):
        return real_consumer(text)

    body = sse(event('chunk', {'text': 'Hi'}), event('chunk', {'text': '!'}), event('done', RECEIPT))

    async def go() -> dict:
        return await make_client(stream_handler(body)).chat_stream(**CHAT_ARGS, on_chunk=wrapper)

    with pytest.warns(RuntimeWarning, match='awaitable'):
        assert asyncio.run(go()) == RECEIPT


def test_the_buffered_path_marks_post_commit_failures_too() -> None:
    """Round 2, should-fix 6.

    Same money invariant, on the path production uses today: a 2xx means the
    bridge already ran the execution, so a failure while reading the body
    may have spent money.
    """

    def oversized(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b'x' * (2 * 1024 * 1024 + 16))

    async def go() -> None:
        await make_client(oversized).chat(**CHAT_ARGS)

    with pytest.raises(ConnectOpenRouterError) as excinfo:
        asyncio.run(go())
    assert excinfo.value.receipt_may_exist is True

    def garbage(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b'{not json')

    async def go2() -> None:
        await make_client(garbage).chat(**CHAT_ARGS)

    with pytest.raises(ConnectOpenRouterError) as excinfo:
        asyncio.run(go2())
    assert excinfo.value.receipt_may_exist is True

    # A denial is pre-commit: nothing ran, retrying under a fresh key is safe.
    def denied(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={'code': 'HUB_R1_DENIED'})

    async def go3() -> None:
        await make_client(denied).chat(**CHAT_ARGS)

    with pytest.raises(ConnectOpenRouterError) as excinfo:
        asyncio.run(go3())
    assert excinfo.value.receipt_may_exist is False


def test_a_byte_order_mark_does_not_swallow_the_first_event() -> None:
    """Round 2, nit 10: a BOM glued itself to the first field name and
    demoted the whole event to an ignored unknown one."""
    body = '﻿' + event('chunk', {'text': 'Hi'}) + event('done', RECEIPT)
    seen: list[str] = []

    async def go() -> dict:
        return await make_client(stream_handler(body)).chat_stream(**CHAT_ARGS, on_chunk=seen.append)

    assert asyncio.run(go()) == RECEIPT
    assert seen == ['Hi']


# --------------------------------------------------------------------------
# Round 3 adversarial review -- regression locks
# --------------------------------------------------------------------------


def test_a_bridge_that_is_not_running_is_a_connect_error_not_a_raw_httpx_error() -> None:
    """Round 3, blocking 1.

    The single most likely failure of a local desktop bridge is that it is
    not running. `client.stream(...)` sat outside the try, so this escaped as
    a raw httpx exception -- and a caller following this module's own
    docstring writes `except ConnectOpenRouterError` and would not catch its
    most common failure at all.
    """
    for exc in (
        httpx.ConnectError('connection refused'),
        httpx.ReadTimeout('wedged'),
        httpx.RemoteProtocolError('garbage status line'),
    ):
        def handler(request: httpx.Request, exc=exc) -> httpx.Response:
            raise exc

        with pytest.raises(ConnectOpenRouterError) as excinfo:
            run_stream(handler)
        # Nothing ran, so retrying under a fresh key is safe.
        assert excinfo.value.receipt_may_exist is False


def test_the_buffered_path_also_flags_unanticipated_post_commit_failures() -> None:
    """Round 3, blocking 2.

    httpx.DecodingError is a RequestError, not a TransportError, so it slipped
    past the three named types -- reaching the caller with no flag at all
    after the bridge had already committed to 200.
    """

    def decoding_failure(request: httpx.Request) -> httpx.Response:
        # Raised while READING the body, which is when a real socket
        # surfaces a mislabelled content-encoding: the 200 is already
        # committed, so the bridge may already have run the execution.
        async def parts():
            yield b'{"authorized":'
            raise httpx.DecodingError('incorrect header check')

        return httpx.Response(200, content=parts())

    async def go() -> None:
        await make_client(decoding_failure).chat(**CHAT_ARGS)

    with pytest.raises(ConnectOpenRouterError) as excinfo:
        asyncio.run(go())
    assert excinfo.value.receipt_may_exist is True


def test_an_oversized_frame_does_not_discard_a_receipt_sitting_behind_it() -> None:
    """Round 3, should-fix 3.

    By the time an oversized block is delimited its memory is already
    allocated, so rejecting on the spot saves nothing -- and it threw away a
    terminal receipt that was already fully buffered and decodable.
    """
    body = sse(
        event('chunk', {'text': 'x' * (300 * 1024)}),
        event('done', RECEIPT),
    )
    assert run_stream(stream_handler(body, piece_size=len(body))) == RECEIPT
    assert run_stream(stream_handler(body, piece_size=64 * 1024)) == RECEIPT


def test_an_oversized_frame_with_no_receipt_behind_it_still_fails() -> None:
    """The counterpart: relaxing the ordering must not remove the bound."""
    body = event('chunk', {'text': 'x' * (300 * 1024)})
    with pytest.raises(ConnectOpenRouterError) as excinfo:
        run_stream(stream_handler(body, piece_size=64 * 1024))
    assert excinfo.value.code == 'CONNECT_STREAM_TOO_LARGE'
    assert excinfo.value.receipt_may_exist is True


def test_an_async_generator_on_chunk_warns_rather_than_silently_dropping_deltas() -> None:
    """Round 3, nit 7: isawaitable() is False for an async generator, so this
    shape missed the warn-and-disable path the coroutine shape got."""

    def gen_consumer(text: str):
        async def inner():
            yield text
        return inner()

    body = sse(event('chunk', {'text': 'Hi'}), event('done', RECEIPT))

    async def go() -> dict:
        return await make_client(stream_handler(body)).chat_stream(**CHAT_ARGS, on_chunk=gen_consumer)

    with pytest.warns(RuntimeWarning, match='awaitable'):
        assert asyncio.run(go()) == RECEIPT


def test_a_delimiterless_oversized_buffer_is_still_bounded_between_reads() -> None:
    """The pending check now measures characters, which is exact in the
    direction that rejects (a UTF-8 character is never under one byte) and
    avoids re-encoding the whole buffer on every read."""
    body = 'event: chunk\ndata: ' + ('x' * (300 * 1024))
    with pytest.raises(ConnectOpenRouterError) as excinfo:
        run_stream(stream_handler(body, piece_size=32 * 1024))
    assert excinfo.value.code == 'CONNECT_STREAM_TOO_LARGE'
