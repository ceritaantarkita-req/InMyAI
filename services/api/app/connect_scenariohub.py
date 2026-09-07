from __future__ import annotations
# Q11.3 Piece 3 (2026-09-04): InMyAI-side client for governed bounded
# scenario execution, gated by InMyHub's scenario-execution-r1-authority.mjs
# (merged as InMyHub PR #42, HTTP-exposed at /api/scenario-execution/r1/* by
# PR #43). This module mirrors connect_inmyrnd.py's structure and shared
# HTTP core (same error-class shape, same bounded validators, same
# httpx.AsyncClient/streaming-body-size-bounded _bounded_json_request()
# core) -- confirmed against connect_inmyrnd.py's real, current content
# this session (559 lines, `cat`'d in full).
#
# ONLY ONE CLIENT CLASS, UNLIKE SANDBOX AND R&D (both of which needed two):
# Sandbox and R&D each call a *separate product's own* HTTP API as the real
# execution step (InMySandbox's /api/sandboxes*, InMyR&D's
# /api/experiments/:id/run) -- so both needed a second, InMyAI-side runtime
# client talking to that other loopback service. Scenario execution has no
# such second product: the "executor" is InMyAI's own scenario_runtime.py,
# already running in-process (see main.py's wiring -- it calls
# scenario_runtime.run_scenario()/replay_scenario() directly, no HTTP call
# involved). So this module defines only ScenarioAuthorityClient, the Hub
# boundary -- there is no InMyScenarioRuntimeClient because there is no
# second loopback API to call.
#
# THE DIGEST IS A FREE DESIGN CHOICE, NOT A PORTED FOREIGN FUNCTION (unlike
# R&D's experiment_digest(), which is a byte-for-byte port of InMyR&D's own
# pre-existing experimentDigest()): scenarioDigest has no foreign function
# it must match bit-for-bit, only Hub's own generic sha256:<64 hex> shape
# (confirmed against the real, merged validateAuthorizeRequest()). So
# scenario_digest() below reuses the SAME sorted-keys canonical-JSON
# convention scenario_runtime.py's own _canonical_json() already uses
# (confirmed identical this session: json.dumps(value, sort_keys=True,
# separators=(',', ':'), ensure_ascii=False)) -- one digest convention for
# the whole system, rather than inventing a second one. See
# test_connect_scenariohub.py's TestScenarioDigest for an explicit
# consistency check against a real BUILTIN_SCENARIOS script's stored
# script_json, so this can never silently drift from scenario_runtime.py's
# own canonicalization if either is edited independently in the future.
#
# TRACE_HASH MUST BE PREFIXED BEFORE IT REACHES HUB: scenario_runtime.py's
# `trace_hash` column is unprefixed 64-hex (confirmed against its real,
# current content this session). Hub's normalizedScenarioOutputs()
# (confirmed against the real, merged source) silently normalizes an
# unprefixed value to `null` rather than erroring -- so main.py's wiring
# (not this module) is responsible for prefixing trace_hash/
# replay_of_trace_hash with 'sha256:' before building the executor receipt.
# This module does not touch trace_hash directly; it is listed here only so
# the load-bearing reason is not lost to whoever next edits main.py's
# wiring.
#
# OUTCOME IS ALWAYS 'completed' IN THIS DESIGN: scenario_runtime.py's real
# run_scenario()/replay_scenario() (confirmed against their current, full
# content) wrap their entire body in try/except Exception -- on failure
# they mark the DB row status='failed' and then RE-RAISE the original
# exception, exactly like R&D's evaluateExperiment() aborting before a
# receipt is ever built (there is no code path where a caller receives a
# successful return whose *own* internal status is 'failed' -- either it
# returns a completed run, or it raises). So main.py's wiring, like
# rnd_run(), never has a real reason to build a receipt with
# outcome='failed' today. record_execution() below still accepts 'failed'
# as a structurally valid receipt.outcome (Hub's own ALLOWED_OUTCOMES for
# this provider is {'completed', 'failed'}, confirmed against the real,
# merged validateExecutorReceipt()), because Hub requires it as an allowed
# value, but no code path in this module's caller is expected to produce it
# today.
#
# REAL-SIDE-EFFECT ERROR FLAG: mirrors RndExecutionError's
# execution_may_have_run. There is no separate runtime client here to set
# it from (see above) -- main.py's wiring sets it when constructing the
# HTTPException it raises after a local scenario_runtime call has already
# completed but recording the receipt to Hub then fails, exactly mirroring
# rnd_run()'s own explicit handling of that same failure shape (see
# rnd_run()'s `except RndExecutionError as exc:` tail, confirmed against
# its real, current content this session).
#
# NOT INCLUDED IN THIS CHANGE: wiring this client into main.py, or defining
# InMyAI's POST /api/scenarios/{slug}/run and /replay endpoint bodies. Those
# are this same piece's main.py/schemas.py changes, delivered alongside
# this file in one PR (per Amanda's "lanjut" with the discovery doc's
# stated default: this module is thin enough that a client-module PR +
# wiring PR split, as Sandbox/R&D used, is not warranted here).
import hashlib
import ipaddress
import json
import re
from typing import Any
from urllib.parse import urlparse

import httpx

_MAX_RESPONSE_BYTES = 2 * 1024 * 1024
_IDEMPOTENCY_KEY = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._:/-]{7,255}$')
_SHA256_DIGEST = re.compile(r'^sha256:[0-9a-f]{64}$')
# Scenario slugs are always looked up against InMyAI's own scenario_runtime
# registry (scenario_runtime.get_scenario(slug), which raises KeyError --
# turned into a 404 by main.py -- for anything not already a known,
# built-in scenario) before this module ever sees the value, so this is a
# defense-in-depth bound rather than the sole gate. Matches the one real
# example this program has (`q11-3-context-recall-v1`): lowercase
# alphanumeric segments joined by single hyphens.
_SCENARIO_SLUG = re.compile(r'^[a-z0-9]+(?:-[a-z0-9]+)*$')
# Confirmed against the real, merged scenario-execution-r1-authority.mjs:
# authorizationId is generated as opaqueId('scenauth', {...}), where
# opaqueId() returns `${prefix}_${sha256(canonicalJson(value)).digest(
# 'base64url').slice(0, 48)}` -- base64url charset, 48 chars after the
# prefix. Bounded to a wider range here (16-96), same defense-in-depth
# style connect_inmyrnd.py's own _AUTHORIZATION_ID uses rather than pinning
# the exact length Hub happens to generate today.
_AUTHORIZATION_ID = re.compile(r'^scenauth_[A-Za-z0-9_-]{16,96}$')
# executorReceipt.receiptId is generated by InMyAI itself (main.py's
# wiring, mirroring rnd_run()'s own `'rndrct_' + uuid4().hex + uuid4().hex`
# pattern exactly -- confirmed against rnd_run()'s real, current content
# this session), not by Hub's opaqueId() -- Hub only validates it against
# its own RECEIPT_ID pattern. 'scenrct_' follows the same short-prefix
# family already confirmed real for this provider (scenauth_, and Hub's own
# internal scenhubi_/scenhubr_ ids), and uuid4().hex*2 is 64 lowercase-hex
# characters, well inside this bound and inside the same character class
# rnd's real 'rndrct_' + 64 hex chars already satisfies today.
_RECEIPT_ID = re.compile(r'^scenrct_[A-Za-z0-9_-]{16,96}$')
# Hub's own ALLOWED_OUTCOMES for scenario-execution/r1 (scenario-execution-
# r1-authority.mjs's validateExecutorReceipt()), confirmed against the
# real, merged source -- exactly two values, same as R&D's.
_ALLOWED_OUTCOMES = frozenset({'completed', 'failed'})


class ScenarioExecutionError(RuntimeError):
    """A failure at InMyHub's scenario-execution/r1 authority boundary. See
    this module's header for `execution_may_have_run` (set by main.py's
    wiring, not by this class itself -- this module has no separate
    real-side-effect call of its own to set it from).
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int = 503,
        code: str = 'SCENARIO_EXECUTION_ERROR',
        execution_may_have_run: bool = False,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.execution_may_have_run = execution_may_have_run


def _bounded_string(value: Any, label: str, *, minimum: int = 1, maximum: int = 4096) -> str:
    if not isinstance(value, str) or not minimum <= len(value) <= maximum or '\x00' in value:
        raise ValueError(f'{label} must be a bounded NUL-free string.')
    if value.strip() != value:
        raise ValueError(f'{label} cannot have surrounding whitespace.')
    return value


def _normalize_loopback_base_url(value: str, *, label: str) -> str:
    raw = _bounded_string(value, label, minimum=8, maximum=256)
    parsed = urlparse(raw)
    if parsed.scheme != 'http':
        raise ValueError(f'{label} must use plain HTTP on loopback.')
    if parsed.username or parsed.password:
        raise ValueError(f'{label} cannot contain credentials.')
    if parsed.query or parsed.fragment or parsed.path not in ('', '/'):
        raise ValueError(f'{label} cannot contain path, query, or fragment data.')
    if parsed.port is None:
        raise ValueError(f'{label} must include an explicit port.')
    try:
        address = ipaddress.ip_address(parsed.hostname or '')
    except ValueError as exc:
        raise ValueError(f'{label} must use an explicit loopback IP literal.') from exc
    if not address.is_loopback:
        raise ValueError(f'{label} must be loopback-only.')
    host = f'[{address.compressed}]' if address.version == 6 else address.compressed
    return f'http://{host}:{parsed.port}'


def _normalize_bearer_token(value: str) -> str:
    token = _bounded_string(value, 'Hub service token', minimum=16, maximum=8192)
    if re.search(r'\s', token):
        raise ValueError('Hub service token is malformed.')
    return token


def _validate_idempotency_key(value: str) -> str:
    candidate = _bounded_string(value, 'idempotency_key', minimum=8, maximum=256)
    if not _IDEMPOTENCY_KEY.fullmatch(candidate):
        raise ValueError('idempotency_key is invalid.')
    return candidate


def _validate_digest(value: str, label: str) -> str:
    candidate = _bounded_string(value, label, maximum=71)
    if not _SHA256_DIGEST.fullmatch(candidate):
        raise ValueError(f'{label} must be sha256:<64 lowercase hex characters>.')
    return candidate


def _validate_scenario_slug(value: str) -> str:
    candidate = _bounded_string(value, 'scenario_slug', maximum=64)
    if not _SCENARIO_SLUG.fullmatch(candidate):
        raise ValueError('scenario_slug is invalid.')
    return candidate


def _validate_scenario_version(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError('scenario_version must be a positive integer.')
    return value


def _validate_authorization_id(value: str) -> str:
    candidate = _bounded_string(value, 'authorization_id', maximum=101)
    if not _AUTHORIZATION_ID.fullmatch(candidate):
        raise ValueError('authorization_id is invalid.')
    return candidate


def scenario_digest(script: Any) -> str:
    """Sorted-keys canonical JSON over a scenario's script value, matching
    scenario_runtime.py's own `_canonical_json()` convention byte-for-byte
    (confirmed identical this session: sort_keys=True, compact separators,
    ensure_ascii=False -- non-ASCII matters here the same way Piece 2's
    discovery already flagged for R&D's experiment_digest(), since scenario
    `title`/step `instruction` fields are free text). Unlike
    connect_inmyrnd.py's experiment_digest(), this is NOT a port of a
    foreign function -- there is no pre-existing JS digest this must match
    bit-for-bit, only Hub's generic sha256:<64 hex> shape. Callers should
    pass the *parsed* script value (e.g. `json.loads(scenario['script_json'])`),
    not the already-serialized string -- see test_connect_scenariohub.py's
    TestScenarioDigest for an explicit cross-check that this reproduces the
    same digest as hashing scenario_runtime.py's own stored `script_json`
    text directly, so the two canonicalizations can never silently drift
    apart.
    """
    encoded = json.dumps(script, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
    return f'sha256:{hashlib.sha256(encoded.encode("utf-8")).hexdigest()}'


def scenario_digest_from_canonical_json(canonical_json: str) -> str:
    """Same digest as scenario_digest(), but takes an already-canonical
    JSON string directly -- e.g. scenario_runtime.py's own stored
    `script_json` field, which get_scenario() confirms is already written
    via that module's _canonical_json() (identical convention: sort_keys,
    compact separators, ensure_ascii=False -- see scenario_digest()'s own
    docstring). Hashing the stored string directly avoids a redundant
    parse-and-re-serialize round trip in main.py's wiring, and means
    main.py's scenario endpoints need no `json` import of their own for
    this. test_connect_scenariohub.py's TestScenarioDigest cross-checks
    this against scenario_digest(json.loads(...)) on the same value to
    confirm the two entry points can never silently diverge.
    """
    return f'sha256:{hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()}'


def scenario_step_count(task_ids_json: str | None) -> int | None:
    """Parses scenario_runtime.py's stored `task_ids_json` column (a JSON-
    encoded list, one task id per script step -- confirmed against its
    real, current content this session: run_scenario() walks the script
    one agent_runtime task per step) into a step count for the executor
    receipt's `outputs.stepCount`. Returns None if the value is missing or
    not a JSON array, rather than raising -- stepCount is informational
    (Hub's normalizedScenarioOutputs() already treats a non-int as null),
    not something a malformed value should abort a receipt over. Kept here
    rather than inline in main.py so scenario endpoints need no `json`
    import of their own for this either -- see
    scenario_digest_from_canonical_json()'s docstring for the same reason.
    """
    if not isinstance(task_ids_json, str) or not task_ids_json:
        return None
    try:
        parsed = json.loads(task_ids_json)
    except (json.JSONDecodeError, ValueError):
        return None
    return len(parsed) if isinstance(parsed, list) else None


async def _bounded_json_request(
    *,
    base_url: str,
    path: str,
    method: str,
    headers: dict[str, str],
    payload: dict[str, Any] | None,
    timeout_seconds: float,
    transport: httpx.AsyncBaseTransport | None,
    error_cls: type[ScenarioExecutionError],
    unavailable_message: str,
) -> tuple[dict[str, Any], bool]:
    """Shared HTTP core, identical in shape to connect_inmyrnd.py's
    _bounded_json_request(): bounded-size streamed read, strict JSON-object
    response shape, and the same committed-before-we-know-the-outcome
    tracking. `committed` means the far side answered with a 2xx status
    line (it believes the operation succeeded) -- the point past which we
    cannot safely assume "it did not happen" if reading/decoding the rest
    of that response then fails. A clean non-2xx response is not
    committed. Returns (decoded_body, committed).
    """
    timeout = httpx.Timeout(timeout_seconds)
    committed = False
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False, transport=transport) as client:
        try:
            async with client.stream(method, f'{base_url}{path}', headers=headers, json=payload) as response:
                committed = 200 <= response.status_code < 300
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > _MAX_RESPONSE_BYTES:
                        raise error_cls('Response exceeded the bounded response size.', execution_may_have_run=committed)
                try:
                    decoded = json.loads(body.decode('utf-8')) if body else {}
                except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, ValueError) as exc:
                    raise error_cls('Response was not valid JSON.', execution_may_have_run=committed) from exc
                if not isinstance(decoded, dict):
                    raise error_cls('Response must be a JSON object.', execution_may_have_run=committed)
                if response.status_code < 200 or response.status_code >= 300:
                    code = decoded.get('code') if isinstance(decoded.get('code'), str) else 'HTTP_ERROR'
                    safe_code = code if re.fullmatch(r'[A-Z0-9_:-]{2,128}', code) else 'HTTP_ERROR'
                    error_message = decoded.get('error') if isinstance(decoded.get('error'), str) else 'Request failed.'
                    raise error_cls(
                        f'{error_message} ({safe_code})',
                        status_code=response.status_code,
                        code=safe_code,
                        execution_may_have_run=committed,
                    )
                return decoded, committed
        except error_cls:
            raise
        except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError) as exc:
            raise error_cls(unavailable_message, execution_may_have_run=committed) from exc
        except Exception as exc:  # noqa: BLE001
            raise error_cls('Request failed unexpectedly.', execution_may_have_run=committed) from exc


class ScenarioAuthorityClient:
    """Server-side client for InMyHub's /api/scenario-execution/r1/*
    authority routes (server/scenario-execution-r1-authority.mjs, merged
    InMyHub PR #42, HTTP-exposed by PR #43). Pure bookkeeping: every call
    here is safe to retry, `execution_may_have_run` is never set on errors
    raised from this class (see this module's header -- main.py's wiring
    sets it, not this client, since the real side effect -- the local
    scenario_runtime call -- happens outside this class entirely).

    providerId is always 'inmyai-scenario' and actionId is always
    'scenario.run' -- the only action InMyHub's R1 scenario execution
    policy allows (policy.allowedProviders['inmyai-scenario'].actions,
    confirmed against the real, merged validateAuthorizeRequest()) -- so,
    unlike a hypothetical multi-action client, these are fixed here rather
    than accepted as caller-supplied parameters. This also covers replay:
    per the discovery doc's resolved open question, replay is not a
    distinct gated action -- it is an ordinary 'scenario.run' authorization
    that happens to also carry replayOfTraceHash/replayMatch in its
    receipt outputs.
    """

    def __init__(
        self,
        *,
        base_url: str,
        hub_service_token: str,
        timeout_seconds: float = 20.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = _normalize_loopback_base_url(base_url, label='hub_base_url')
        self._token = _normalize_bearer_token(hub_service_token)
        if not isinstance(timeout_seconds, (int, float)) or isinstance(timeout_seconds, bool) or not 1 <= float(timeout_seconds) <= 60:
            raise ValueError('Hub authority timeout must be between 1 and 60 seconds.')
        self.timeout_seconds = float(timeout_seconds)
        self.transport = transport

    async def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        if method not in {'GET', 'POST'} or not path.startswith('/api/scenario-execution/r1/'):
            raise ValueError('Scenario authority request shape is invalid.')
        headers = {'accept': 'application/json', 'authorization': f'Bearer {self._token}'}
        if method == 'POST':
            headers['content-type'] = 'application/json'
        decoded, _committed = await _bounded_json_request(
            base_url=self.base_url,
            path=path,
            method=method,
            headers=headers,
            payload=payload if method == 'POST' else None,
            timeout_seconds=self.timeout_seconds,
            transport=self.transport,
            error_cls=ScenarioExecutionError,
            unavailable_message='InMyHub scenario execution authority is unavailable.',
        )
        return decoded

    async def status(self) -> dict[str, Any]:
        return await self._request('GET', '/api/scenario-execution/r1/status')

    async def authorize(
        self,
        *,
        workflow_run_id: str,
        delegation_id: str,
        scenario_slug: str,
        scenario_version: int,
        scenario_digest: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        return await self._request('POST', '/api/scenario-execution/r1/authorize', {
            'workflowRunId': _bounded_string(workflow_run_id, 'workflow_run_id', minimum=3, maximum=128),
            'delegationId': _bounded_string(delegation_id, 'delegation_id', minimum=3, maximum=128),
            'providerId': 'inmyai-scenario',
            'actionId': 'scenario.run',
            'scenarioSlug': _validate_scenario_slug(scenario_slug),
            'scenarioVersion': _validate_scenario_version(scenario_version),
            'scenarioDigest': _validate_digest(scenario_digest, 'scenario_digest'),
            'idempotencyKey': _validate_idempotency_key(idempotency_key),
        })

    async def record_intent(
        self,
        *,
        workflow_run_id: str,
        delegation_id: str,
        authorization_id: str,
        idempotency_key: str,
        scenario_slug: str,
        scenario_version: int,
        scenario_digest: str,
        started_at: str,
    ) -> dict[str, Any]:
        return await self._request('POST', '/api/scenario-execution/r1/intent', {
            'workflowRunId': _bounded_string(workflow_run_id, 'workflow_run_id', minimum=3, maximum=128),
            'delegationId': _bounded_string(delegation_id, 'delegation_id', minimum=3, maximum=128),
            'authorizationId': _validate_authorization_id(authorization_id),
            'idempotencyKey': _validate_idempotency_key(idempotency_key),
            'providerId': 'inmyai-scenario',
            'actionId': 'scenario.run',
            'scenarioSlug': _validate_scenario_slug(scenario_slug),
            'scenarioVersion': _validate_scenario_version(scenario_version),
            'scenarioDigest': _validate_digest(scenario_digest, 'scenario_digest'),
            'startedAt': _bounded_string(started_at, 'started_at', maximum=64),
        })

    async def record_execution(
        self,
        *,
        workflow_run_id: str,
        delegation_id: str,
        authorization_id: str,
        idempotency_key: str,
        scenario_slug: str,
        scenario_version: int,
        scenario_digest: str,
        recorded_at: str,
        executor_receipt: dict[str, Any],
    ) -> dict[str, Any]:
        if not isinstance(executor_receipt, dict):
            raise ValueError('executor_receipt must be an object.')
        outcome = executor_receipt.get('outcome')
        if outcome not in _ALLOWED_OUTCOMES:
            raise ValueError('executor_receipt.outcome must be one of completed, failed.')
        if not _RECEIPT_ID.fullmatch(str(executor_receipt.get('receiptId', ''))):
            raise ValueError('executor_receipt.receiptId is invalid.')
        return await self._request('POST', '/api/scenario-execution/r1/record', {
            'workflowRunId': _bounded_string(workflow_run_id, 'workflow_run_id', minimum=3, maximum=128),
            'delegationId': _bounded_string(delegation_id, 'delegation_id', minimum=3, maximum=128),
            'authorizationId': _validate_authorization_id(authorization_id),
            'idempotencyKey': _validate_idempotency_key(idempotency_key),
            'providerId': 'inmyai-scenario',
            'actionId': 'scenario.run',
            'scenarioSlug': _validate_scenario_slug(scenario_slug),
            'scenarioVersion': _validate_scenario_version(scenario_version),
            'scenarioDigest': _validate_digest(scenario_digest, 'scenario_digest'),
            'recordedAt': _bounded_string(recorded_at, 'recorded_at', maximum=64),
            'executorReceipt': executor_receipt,
        })


def create_scenario_authority_client(
    *,
    base_url: str,
    hub_service_token: str,
    timeout_seconds: float = 20.0,
) -> ScenarioAuthorityClient:
    return ScenarioAuthorityClient(base_url=base_url, hub_service_token=hub_service_token, timeout_seconds=timeout_seconds)
