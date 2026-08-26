from __future__ import annotations

# Q11.1 (Phase 10, 2026-08-25): InMyAI-side clients for real InMySandbox R1
# execution, gated by InMyHub's sandbox-execution-r1-authority.mjs (merged as
# commit 07103c2, HTTP-exposed at /api/sandbox-execution/r1/* by the
# following Piece 2 commit). This is the module `provider_execution_contract.
# py`'s docstring called "CONNECT_HTTP_BRIDGE_RUNTIME" for the OpenRouter
# path -- but see below for why the InMySandbox shape is NOT a copy of that
# module. It never became load-bearing (see the Piece 3 design note this
# module's PR references: plan_governed_provider_execution() has zero real
# callers in this codebase). The pattern actually proven live end-to-end
# (docs/phase5-openrouter-live-e2e-acceptance-v1.md) is connect_openrouter.
# py's ConnectOpenRouterClient, wired through main.py's _openrouter_client().
# This module mirrors THAT pattern -- same error-class shape, same bounded
# validators, same httpx.AsyncClient/streaming-body-size-bounded _request()
# core -- adapted to InMySandbox's real, already-shipped execution API
# (server.mjs's /api/sandboxes* routes) instead of a second copy of the
# dead planner.
#
# TWO client classes, not one, because there are TWO separate loopback trust
# boundaries here, unlike OpenRouter's single InMyConnect bridge:
#   - SandboxAuthorityClient talks to InMyHub's /api/sandbox-execution/r1/*
#     -- credentialed service auth (the same agent:inmyai Bearer token
#     already used for InMyConnect), bookkeeping only, no real side effects.
#   - InMySandboxRuntimeClient talks to InMySandbox's /api/sandboxes* --
#     no credential concept at all (InMySandbox enforces loopback via a
#     strict Host/Origin check, not a Bearer token; see its server.mjs
#     assertLocalRequest()), and DOES have real side effects: it spawns and
#     runs a real Docker container.
# There is no InMyConnect-equivalent third bridge process for InMySandbox.
# That bridge exists for OpenRouter specifically to vault a third-party API
# key InMyAI and Hub must never see. InMySandbox holds no such secret --
# it is pure local Docker execution -- so InMyAI can safely be the direct
# orchestrator: authorize+intent with Hub, then create+run directly against
# InMySandbox, then record the receipt back to Hub. See this module's PR
# description for the fuller reasoning (mirrors the Piece 3 design note
# already in the project's own history).
#
# DIGEST CONTRACT: Hub's sandbox-execution-r1-authority.mjs never recomputes
# policyDigest/commandDigest from raw data -- it only requires the same
# opaque string across authorize -> intent -> record (see that module's
# validateExecutorReceipt(), which compares receipt fields against the
# stored authorization binding, never against a freshly-hashed policy). The
# digest is therefore a caller-side commitment, not a Hub-verified one. This
# client computes it as sha256 over the EXACT canonical JSON of the policy /
# command object it is about to send to InMySandbox, using the same
# sort-keys-compact-separators canonicalization Hub's own canonicalJson()
# uses (server/sandbox-execution-r1-authority.mjs) -- not because Hub checks
# it, but so a human auditing an authorization record can recompute the
# digest from the real InMySandbox request logs and confirm they match.
#
# REAL-SIDE-EFFECT ERROR FLAG: mirrors ConnectOpenRouterClient's
# receipt_may_exist, renamed execution_may_have_run because there is no
# money at stake here, only real Docker resource consumption and a job that
# may already be running. Same "committed" model as connect_openrouter.py:
# committed=True means InMySandbox answered with a 2xx status line -- i.e.
# it BELIEVES the operation succeeded -- and something then went wrong while
# we were reading/decoding that success response (truncated body, dropped
# connection, oversized response). A clean non-2xx response is NOT
# ambiguous: InMySandbox's own handler ran and is reporting failure, so no
# container was created / no job started, and it is safe to retry as-is.
# It is set on errors raised from InMySandboxRuntimeClient.create() and
# .run() specifically -- the two calls that cause a real side effect --
# never on Hub-side authority calls (authorize/intent/record are pure
# bookkeeping, always safe to retry regardless of status code). A caller
# must not retry a create()/run() that failed with this flag set under a
# NEW idempotencyKey; the container or job may already exist. This module
# intentionally does NOT decide what to do about that -- it surfaces the
# flag and leaves recovery policy to its caller, same separation
# ConnectOpenRouterClient uses.
#
# NOT INCLUDED IN THIS CHANGE: wiring these clients into main.py, or
# defining InMyAI's own user-facing endpoint/contract for "run this in
# InMySandbox". That is a real product decision (how a chat turn or tool
# call actually triggers this) this module does not make for the caller --
# left for a following, separately-reviewable piece, same as how Piece 1
# and Piece 2 shipped as independent PRs rather than one large one.

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
_AUTHORIZATION_ID = re.compile(r'^sbxauth_[A-Za-z0-9_-]{16,96}$')
_RECEIPT_ID = re.compile(r'^sbxrct_[A-Za-z0-9_-]{16,96}$')
_SANDBOX_ID = re.compile(r'^sbx_[A-Za-z0-9-]{8,64}$')
_ALLOWED_OUTCOMES = frozenset({'completed', 'timed_out', 'failed'})


class SandboxExecutionError(RuntimeError):
    """A failure at either the Hub authority boundary or the InMySandbox
    runtime boundary. See this module's header for `execution_may_have_run`.
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int = 503,
        code: str = 'SANDBOX_EXECUTION_ERROR',
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


def _validate_authorization_id(value: str) -> str:
    candidate = _bounded_string(value, 'authorization_id', maximum=101)
    if not _AUTHORIZATION_ID.fullmatch(candidate):
        raise ValueError('authorization_id is invalid.')
    return candidate


def _validate_sandbox_id(value: str) -> str:
    candidate = _bounded_string(value, 'sandbox_id', maximum=69)
    if not _SANDBOX_ID.fullmatch(candidate):
        raise ValueError('sandbox_id is invalid.')
    return candidate


def canonical_json(value: Any) -> str:
    """Mirrors sandbox-execution-r1-authority.mjs's canonicalJson(): sorted
    object keys, compact separators, stable across key-insertion order.
    """
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True)


def sha256_digest(value: Any) -> str:
    """sha256:<hex> of canonical_json(value) -- see this module's header for
    why this is a caller-side commitment, not something Hub recomputes.
    """
    return f'sha256:{hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()}'


async def _bounded_json_request(
    *,
    base_url: str,
    path: str,
    method: str,
    headers: dict[str, str],
    payload: dict[str, Any] | None,
    timeout_seconds: float,
    transport: httpx.AsyncBaseTransport | None,
    error_cls: type[SandboxExecutionError],
    unavailable_message: str,
) -> tuple[dict[str, Any], bool]:
    """Shared HTTP core for both clients below: bounded-size streamed read,
    strict JSON-object response shape, and the same
    committed-before-we-know-the-outcome tracking connect_openrouter.py's
    _request() uses -- committed here means the far side answered with a
    2xx status line (it believes the operation succeeded), which is the
    point past which we cannot safely assume "it did not happen" if reading
    or decoding the rest of that response then fails. A clean non-2xx
    response is not committed -- the far side ran and is telling us it
    failed. Returns (decoded_body, committed).
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


class SandboxAuthorityClient:
    """Server-side client for InMyHub's /api/sandbox-execution/r1/*
    authority routes (server/sandbox-execution-r1-authority.mjs, HTTP-
    exposed by the Piece 2 change to server/server.mjs). Pure bookkeeping:
    every call here is safe to retry, `execution_may_have_run` is never set
    on errors raised from this class.
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
        if method not in {'GET', 'POST'} or not path.startswith('/api/sandbox-execution/r1/'):
            raise ValueError('Sandbox authority request shape is invalid.')
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
            error_cls=SandboxExecutionError,
            unavailable_message='InMyHub sandbox execution authority is unavailable.',
        )
        return decoded

    async def status(self) -> dict[str, Any]:
        return await self._request('GET', '/api/sandbox-execution/r1/status')

    async def authorize(
        self,
        *,
        workflow_run_id: str,
        delegation_id: str,
        policy_digest: str,
        command_digest: str,
        idempotency_key: str,
        input_digest: str,
        input_bytes: int,
        input_sensitivity: str,
    ) -> dict[str, Any]:
        if not isinstance(input_bytes, int) or isinstance(input_bytes, bool) or not 0 <= input_bytes <= 131072:
            raise ValueError('input_bytes must be an integer between 0 and 131072 (the pinned R1 sandbox policy cap).')
        if input_sensitivity not in ('PUBLIC', 'INTERNAL'):
            raise ValueError('input_sensitivity must be PUBLIC or INTERNAL for R1 sandbox execution.')
        return await self._request('POST', '/api/sandbox-execution/r1/authorize', {
            'workflowRunId': _bounded_string(workflow_run_id, 'workflow_run_id', minimum=3, maximum=128),
            'delegationId': _bounded_string(delegation_id, 'delegation_id', minimum=3, maximum=128),
            'providerId': 'inmysandbox',
            'actionId': 'sandbox.run',
            'policyDigest': _validate_digest(policy_digest, 'policy_digest'),
            'commandDigest': _validate_digest(command_digest, 'command_digest'),
            'idempotencyKey': _validate_idempotency_key(idempotency_key),
            'inputDigest': _validate_digest(input_digest, 'input_digest'),
            'inputBytes': input_bytes,
            'inputSensitivity': input_sensitivity,
        })

    async def record_intent(
        self,
        *,
        workflow_run_id: str,
        delegation_id: str,
        authorization_id: str,
        idempotency_key: str,
        policy_digest: str,
        command_digest: str,
        input_digest: str,
        started_at: str,
    ) -> dict[str, Any]:
        return await self._request('POST', '/api/sandbox-execution/r1/intent', {
            'workflowRunId': _bounded_string(workflow_run_id, 'workflow_run_id', minimum=3, maximum=128),
            'delegationId': _bounded_string(delegation_id, 'delegation_id', minimum=3, maximum=128),
            'authorizationId': _validate_authorization_id(authorization_id),
            'idempotencyKey': _validate_idempotency_key(idempotency_key),
            'providerId': 'inmysandbox',
            'actionId': 'sandbox.run',
            'policyDigest': _validate_digest(policy_digest, 'policy_digest'),
            'commandDigest': _validate_digest(command_digest, 'command_digest'),
            'inputDigest': _validate_digest(input_digest, 'input_digest'),
            'startedAt': _bounded_string(started_at, 'started_at', maximum=64),
        })

    async def record_execution(
        self,
        *,
        workflow_run_id: str,
        delegation_id: str,
        authorization_id: str,
        idempotency_key: str,
        policy_digest: str,
        command_digest: str,
        input_digest: str,
        recorded_at: str,
        executor_receipt: dict[str, Any],
    ) -> dict[str, Any]:
        if not isinstance(executor_receipt, dict):
            raise ValueError('executor_receipt must be an object.')
        outcome = executor_receipt.get('outcome')
        if outcome not in _ALLOWED_OUTCOMES:
            raise ValueError('executor_receipt.outcome must be one of completed, timed_out, failed.')
        _validate_authorization_id(str(executor_receipt.get('authorizationId', '')))
        if not _RECEIPT_ID.fullmatch(str(executor_receipt.get('receiptId', ''))):
            raise ValueError('executor_receipt.receiptId is invalid.')
        return await self._request('POST', '/api/sandbox-execution/r1/record', {
            'workflowRunId': _bounded_string(workflow_run_id, 'workflow_run_id', minimum=3, maximum=128),
            'delegationId': _bounded_string(delegation_id, 'delegation_id', minimum=3, maximum=128),
            'authorizationId': _validate_authorization_id(authorization_id),
            'idempotencyKey': _validate_idempotency_key(idempotency_key),
            'providerId': 'inmysandbox',
            'actionId': 'sandbox.run',
            'policyDigest': _validate_digest(policy_digest, 'policy_digest'),
            'commandDigest': _validate_digest(command_digest, 'command_digest'),
            'inputDigest': _validate_digest(input_digest, 'input_digest'),
            'recordedAt': _bounded_string(recorded_at, 'recorded_at', maximum=64),
            'executorReceipt': executor_receipt,
        })


class InMySandboxRuntimeClient:
    """Server-side client for InMySandbox's own /api/sandboxes* execution
    API (server.mjs, already real and shipped -- this class adds no new
    behavior to InMySandbox itself, it only calls what is already there).

    No Bearer token: InMySandbox has no credential concept in v0.1 (see
    sandbox-execution-r1-authority.mjs's header for why Hub's policy has no
    connectionId field either). InMySandbox instead enforces loopback-only
    via an explicit Host/Origin check (server.mjs's assertLocalRequest()),
    satisfied automatically by using its real loopback base_url as-is.

    `execution_may_have_run` is set on errors from create() and run() only
    when InMySandbox answered 2xx and something then went wrong reading or
    decoding that response -- see this module's header.
    """

    def __init__(
        self,
        *,
        base_url: str,
        timeout_seconds: float = 305.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = _normalize_loopback_base_url(base_url, label='inmysandbox_base_url')
        # 305s, not connect_openrouter.py's 20s default: InMySandbox's own
        # /run route bounds a single job to at most 300000ms (300s) before
        # it reports TIMED_OUT itself (see lib/policy.mjs's ttlSeconds and
        # server.mjs's /run route), and it holds the HTTP response open for
        # the whole synchronous run. This client's timeout must exceed that
        # ceiling or it would abort a job InMySandbox was about to correctly
        # finish and report on its own.
        if not isinstance(timeout_seconds, (int, float)) or isinstance(timeout_seconds, bool) or not 1 <= float(timeout_seconds) <= 305:
            raise ValueError('InMySandbox client timeout must be between 1 and 305 seconds.')
        self.timeout_seconds = float(timeout_seconds)
        self.transport = transport

    async def _request(self, method: str, path: str, payload: dict[str, Any] | None, *, side_effecting: bool) -> dict[str, Any]:
        if method not in {'GET', 'POST', 'DELETE'} or not path.startswith('/api/'):
            raise ValueError('InMySandbox request shape is invalid.')
        headers = {'accept': 'application/json'}
        if method == 'POST':
            headers['content-type'] = 'application/json'
        error_cls = SandboxExecutionError
        try:
            decoded, _committed = await _bounded_json_request(
                base_url=self.base_url,
                path=path,
                method=method,
                headers=headers,
                payload=payload if method == 'POST' else None,
                timeout_seconds=self.timeout_seconds,
                transport=self.transport,
                error_cls=error_cls,
                unavailable_message='InMySandbox local runtime is unavailable.',
            )
        except error_cls as exc:
            if not side_effecting:
                # Non-side-effecting calls (status/list/logs/artifacts) never
                # carry real-side-effect risk regardless of what the shared
                # HTTP core inferred from the response status line.
                raise error_cls(str(exc), status_code=exc.status_code, code=exc.code, execution_may_have_run=False) from exc
            raise
        return decoded

    async def health(self) -> dict[str, Any]:
        return await self._request('GET', '/api/health', None, side_effecting=False)

    async def create_sandbox(self, policy: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(policy, dict):
            raise ValueError('policy must be an object.')
        return await self._request('POST', '/api/sandboxes', {'policy': policy}, side_effecting=True)

    async def run(
        self,
        *,
        sandbox_id: str,
        command: list[str],
        inputs: list[dict[str, Any]] | None = None,
        timeout_ms: int = 60000,
    ) -> dict[str, Any]:
        if not isinstance(command, list) or not command or not all(isinstance(item, str) for item in command):
            raise ValueError('command must be a non-empty list of strings.')
        if not isinstance(timeout_ms, int) or isinstance(timeout_ms, bool) or not 1000 <= timeout_ms <= 300000:
            raise ValueError('timeout_ms must be an integer between 1000 and 300000 (InMySandbox\'s own accepted range).')
        sbx = _validate_sandbox_id(sandbox_id)
        return await self._request('POST', f'/api/sandboxes/{sbx}/run', {
            'command': command,
            'inputs': inputs or [],
            'timeoutMs': timeout_ms,
        }, side_effecting=True)

    async def stop(self, sandbox_id: str) -> dict[str, Any]:
        sbx = _validate_sandbox_id(sandbox_id)
        return await self._request('POST', f'/api/sandboxes/{sbx}/stop', {}, side_effecting=False)

    async def destroy(self, sandbox_id: str) -> dict[str, Any]:
        sbx = _validate_sandbox_id(sandbox_id)
        return await self._request('DELETE', f'/api/sandboxes/{sbx}', None, side_effecting=False)


def create_sandbox_authority_client(
    *,
    base_url: str,
    hub_service_token: str,
    timeout_seconds: float = 20.0,
) -> SandboxAuthorityClient:
    return SandboxAuthorityClient(base_url=base_url, hub_service_token=hub_service_token, timeout_seconds=timeout_seconds)


def create_inmysandbox_runtime_client(
    *,
    base_url: str,
    timeout_seconds: float = 305.0,
) -> InMySandboxRuntimeClient:
    return InMySandboxRuntimeClient(base_url=base_url, timeout_seconds=timeout_seconds)
