from __future__ import annotations

# Q11.2 Piece 3a (2026-09-03): InMyAI-side clients for real InMyR&D R1
# execution, gated by InMyHub's rnd-execution-r1-authority.mjs (merged as
# PR #40, HTTP-exposed at /api/rnd-execution/r1/* by the following Piece 2b
# change, PR #41). This module mirrors connect_inmysandbox.py's structure
# and shared HTTP core (same error-class shape, same bounded validators,
# same httpx.AsyncClient/streaming-body-size-bounded _bounded_json_request()
# core) -- adapted to InMyR&D's real, already-shipped local API
# (server.mjs's /api/experiments* routes) instead of InMySandbox's.
#
# TWO client classes, not one, for the same reason connect_inmysandbox.py
# has two -- there are two separate loopback trust boundaries:
#   - RndAuthorityClient talks to InMyHub's /api/rnd-execution/r1/* --
#     credentialed service auth (the same agent:inmyai Bearer token already
#     used for the OpenRouter and InMySandbox authority clients), bookkeeping
#     only, no real side effects.
#   - InMyRndRuntimeClient talks to InMyR&D's own /api/experiments* --
#     no credential concept at all (InMyR&D enforces loopback via a strict
#     Host/Origin check, not a Bearer token; see its server.mjs
#     assertLocalRequest()). It DOES have a real side effect
#     (POST /api/experiments/:id/run appends a run record and flips the
#     experiment's status to 'evaluated'), even though the computation
#     itself is pure and deterministic (lib/domain.mjs's evaluateExperiment).
# There is no InMyConnect-equivalent third bridge process here either --
# InMyR&D holds no third-party secret, so InMyAI can safely be the direct
# orchestrator: authorize+intent with Hub, then list+run directly against
# InMyR&D, then record the receipt back to Hub.
#
# THE DIGEST IS DIFFERENT FROM SANDBOX'S, ON PURPOSE: Sandbox's
# policyDigest/commandDigest is a caller-side commitment InMyAI itself
# constructs (via canonical_json()/sha256_digest() below, sorted-keys +
# ASCII-escaped, matching Hub's own canonicalJson() convention) -- Hub never
# recomputes it from anything, it only requires the same opaque string
# across authorize -> intent -> record. InMyR&D's experimentDigest is NOT
# that: it is InMyR&D's OWN pre-existing function (lib/domain.mjs), already
# computed and returned inside every evaluateExperiment() result, over a
# payload InMyR&D serializes with plain (non-canonical) JSON.stringify.
# `experiment_digest()` below is a byte-for-byte Python port of that exact
# function -- NOT a reuse of canonical_json()/sha256_digest(), which use a
# different (sorted-keys, ASCII-escaped) convention that would silently
# diverge from InMyR&D's real digest. See that function's own docstring for
# the two concrete ways a naive port gets this wrong; both are cross-checked
# in this module's test suite against real output from InMyR&D's own
# lib/domain.mjs, run under Node, not just asserted in a comment.
#
# REAL-SIDE-EFFECT ERROR FLAG: mirrors SandboxExecutionError's
# execution_may_have_run. Set only on errors raised from
# InMyRndRuntimeClient.run_experiment() -- the one call with a real side
# effect (a run record is appended and the experiment's status changes).
# list_experiments() is a pure read with no side-effect risk, same as
# InMySandboxRuntimeClient.health()/stop()/destroy() are never side-
# effecting regardless of what the shared HTTP core inferred from the
# response status line.
#
# OUTCOME IS ALWAYS 'completed' IN THIS DESIGN (approved via the Piece 3
# discovery doc's open questions): InMyR&D's evaluateExperiment() is pure,
# synchronous, and always succeeds given a valid experiment -- there is no
# equivalent to Sandbox's timedOut/nonzero-exit failure mode inside a
# successful HTTP 201 response. record_execution() below still accepts
# 'failed' as a structurally valid receipt.outcome (Hub's own
# ALLOWED_OUTCOMES for this provider is {'completed', 'failed'} -- note:
# only two values, unlike Sandbox's three; there is no 'timed_out' concept
# for a deterministic scorecard computation) because Hub requires it as an
# allowed value, but no code path in this module's caller is expected to
# produce it today.
#
# NOT INCLUDED IN THIS CHANGE: wiring this client into main.py, or defining
# InMyAI's POST /api/rnd/run endpoint. That is Piece 3b, a separate,
# independently-reviewable PR, same staging Q11.1's Piece 3a/3b split used.

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
_PROJECT_ID = re.compile(r'^rndp_[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')
_EXPERIMENT_ID = re.compile(r'^rnde_[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')
_AUTHORIZATION_ID = re.compile(r'^rndauth_[A-Za-z0-9_-]{16,96}$')
_RECEIPT_ID = re.compile(r'^rndrct_[A-Za-z0-9_-]{16,96}$')
# Hub's own ALLOWED_OUTCOMES for rnd-execution/r1 (rnd-execution-r1-
# authority.mjs) -- exactly two values, confirmed against the real, merged
# source. No 'timed_out': that outcome is specific to Sandbox's real
# process-execution model and does not apply here.
_ALLOWED_OUTCOMES = frozenset({'completed', 'failed'})

# The metric/weight key order InMyR&D's own lib/domain.mjs always builds
# these sub-objects in (Object.fromEntries(METRIC_KEYS.map(...)), where
# METRIC_KEYS = Object.keys(DEFAULT_WEIGHTS) in this fixed order). Needed so
# experiment_digest() below reproduces the exact key order InMyR&D's plain
# (non-sorted) JSON.stringify would produce -- see that function's docstring.
_METRIC_KEYS = ('quality', 'cost', 'latency', 'privacy', 'reliability')


class RndExecutionError(RuntimeError):
    """A failure at either the Hub authority boundary or the InMyR&D
    runtime boundary. See this module's header for `execution_may_have_run`.
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int = 503,
        code: str = 'RND_EXECUTION_ERROR',
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


def _validate_project_id(value: str) -> str:
    candidate = _bounded_string(value, 'project_id', maximum=42)
    if not _PROJECT_ID.fullmatch(candidate):
        raise ValueError('project_id is invalid.')
    return candidate


def _validate_experiment_id(value: str) -> str:
    candidate = _bounded_string(value, 'experiment_id', maximum=42)
    if not _EXPERIMENT_ID.fullmatch(candidate):
        raise ValueError('experiment_id is invalid.')
    return candidate


def _validate_authorization_id(value: str) -> str:
    candidate = _bounded_string(value, 'authorization_id', maximum=101)
    if not _AUTHORIZATION_ID.fullmatch(candidate):
        raise ValueError('authorization_id is invalid.')
    return candidate


def experiment_digest(experiment: dict[str, Any]) -> str:
    """Python port of InMyR&D's real experimentDigest() (lib/domain.mjs,
    confirmed live and unchanged across this program's Piece 2 and Piece 3
    discovery). Cross-checked byte-for-byte against real output from that
    exact function run under Node, including a non-ASCII fixture -- see
    test_connect_inmyrnd.py's TestExperimentDigest.

    Two things a naive Python port gets subtly wrong, both handled
    explicitly here rather than assumed:

    1. This is InMyR&D's plain `JSON.stringify(payload)`, NOT a sorted-keys
       canonical form (unlike this module's own canonical_json(), which
       mirrors Hub's sorted-keys convention for the Sandbox digest -- do
       not reuse that helper here). Key order comes entirely from the
       object literal InMyR&D itself writes (schemaVersion, projectId,
       name, hypothesis, mode, weights, cases -- fixed regardless of the
       source object's own property order), and weights/metrics sub-
       objects are always built by InMyR&D in the fixed order
       quality/cost/latency/privacy/reliability. Building the Python dict
       in that exact key order and serializing with
       `json.dumps(payload, separators=(',', ':'))` (compact, insertion-
       order-preserving) reproduces the same key ordering byte-for-byte.
    2. JS's `JSON.stringify` does NOT ASCII-escape non-ASCII characters;
       Python's `json.dumps` does by default (`ensure_ascii=True`).
       Experiment name/hypothesis/case notes/evidenceRef are free text a
       person types -- accented characters, curly quotes, em dashes, non-
       Latin scripts are all plausible. This function passes
       `ensure_ascii=False` deliberately: using the default would silently
       compute a different digest than InMyR&D whenever a field contains a
       non-ASCII character, and the resulting authorization would either
       never match what InMyR&D itself reports, or (worse) this module's
       own authorize-time digest just would not correspond to the
       experiment InMyR&D is about to actually evaluate.
    """
    payload = {
        'schemaVersion': experiment['schemaVersion'],
        'projectId': experiment['projectId'],
        'name': experiment['name'],
        'hypothesis': experiment['hypothesis'],
        'mode': experiment['mode'],
        'weights': {key: experiment['weights'][key] for key in _METRIC_KEYS},
        'cases': [
            {
                'name': case['name'],
                'evidenceClass': case['evidenceClass'],
                'evidenceRef': case['evidenceRef'],
                'notes': case['notes'],
                'metrics': {key: case['metrics'][key] for key in _METRIC_KEYS},
            }
            for case in experiment['cases']
        ],
    }
    encoded = json.dumps(payload, separators=(',', ':'), ensure_ascii=False)
    return f'sha256:{hashlib.sha256(encoded.encode("utf-8")).hexdigest()}'


async def _bounded_json_request(
    *,
    base_url: str,
    path: str,
    method: str,
    headers: dict[str, str],
    payload: dict[str, Any] | None,
    timeout_seconds: float,
    transport: httpx.AsyncBaseTransport | None,
    error_cls: type[RndExecutionError],
    unavailable_message: str,
) -> tuple[dict[str, Any], bool]:
    """Shared HTTP core, identical in shape to connect_inmysandbox.py's
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


class RndAuthorityClient:
    """Server-side client for InMyHub's /api/rnd-execution/r1/* authority
    routes (server/rnd-execution-r1-authority.mjs, merged PR #40, HTTP-
    exposed by PR #41). Pure bookkeeping: every call here is safe to retry,
    `execution_may_have_run` is never set on errors raised from this class.

    providerId is always 'inmyrnd' and actionId is always 'experiment.run'
    -- the only action InMyHub's R1 R&D execution policy currently allows
    (policy.allowedProviders.inmyrnd.actions) -- so, unlike a hypothetical
    multi-action client, these are fixed here rather than accepted as
    caller-supplied parameters.
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
        if method not in {'GET', 'POST'} or not path.startswith('/api/rnd-execution/r1/'):
            raise ValueError('Rnd authority request shape is invalid.')
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
            error_cls=RndExecutionError,
            unavailable_message='InMyHub R&D execution authority is unavailable.',
        )
        return decoded

    async def status(self) -> dict[str, Any]:
        return await self._request('GET', '/api/rnd-execution/r1/status')

    async def authorize(
        self,
        *,
        workflow_run_id: str,
        delegation_id: str,
        project_id: str,
        experiment_id: str,
        experiment_digest: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        return await self._request('POST', '/api/rnd-execution/r1/authorize', {
            'workflowRunId': _bounded_string(workflow_run_id, 'workflow_run_id', minimum=3, maximum=128),
            'delegationId': _bounded_string(delegation_id, 'delegation_id', minimum=3, maximum=128),
            'providerId': 'inmyrnd',
            'actionId': 'experiment.run',
            'projectId': _validate_project_id(project_id),
            'experimentId': _validate_experiment_id(experiment_id),
            'experimentDigest': _validate_digest(experiment_digest, 'experiment_digest'),
            'idempotencyKey': _validate_idempotency_key(idempotency_key),
        })

    async def record_intent(
        self,
        *,
        workflow_run_id: str,
        delegation_id: str,
        authorization_id: str,
        idempotency_key: str,
        project_id: str,
        experiment_id: str,
        experiment_digest: str,
        started_at: str,
    ) -> dict[str, Any]:
        return await self._request('POST', '/api/rnd-execution/r1/intent', {
            'workflowRunId': _bounded_string(workflow_run_id, 'workflow_run_id', minimum=3, maximum=128),
            'delegationId': _bounded_string(delegation_id, 'delegation_id', minimum=3, maximum=128),
            'authorizationId': _validate_authorization_id(authorization_id),
            'idempotencyKey': _validate_idempotency_key(idempotency_key),
            'providerId': 'inmyrnd',
            'actionId': 'experiment.run',
            'projectId': _validate_project_id(project_id),
            'experimentId': _validate_experiment_id(experiment_id),
            'experimentDigest': _validate_digest(experiment_digest, 'experiment_digest'),
            'startedAt': _bounded_string(started_at, 'started_at', maximum=64),
        })

    async def record_execution(
        self,
        *,
        workflow_run_id: str,
        delegation_id: str,
        authorization_id: str,
        idempotency_key: str,
        project_id: str,
        experiment_id: str,
        experiment_digest: str,
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
        return await self._request('POST', '/api/rnd-execution/r1/record', {
            'workflowRunId': _bounded_string(workflow_run_id, 'workflow_run_id', minimum=3, maximum=128),
            'delegationId': _bounded_string(delegation_id, 'delegation_id', minimum=3, maximum=128),
            'authorizationId': _validate_authorization_id(authorization_id),
            'idempotencyKey': _validate_idempotency_key(idempotency_key),
            'providerId': 'inmyrnd',
            'actionId': 'experiment.run',
            'projectId': _validate_project_id(project_id),
            'experimentId': _validate_experiment_id(experiment_id),
            'experimentDigest': _validate_digest(experiment_digest, 'experiment_digest'),
            'recordedAt': _bounded_string(recorded_at, 'recorded_at', maximum=64),
            'executorReceipt': executor_receipt,
        })


class InMyRndRuntimeClient:
    """Server-side client for InMyR&D's own /api/experiments* API
    (server.mjs, already real and shipped -- this class adds no new
    behavior to InMyR&D itself, it only calls what is already there). No
    Bearer token: InMyR&D has no credential concept in v0.1, same as
    InMySandbox -- it instead enforces loopback-only via an explicit
    Host/Origin check (server.mjs's assertLocalRequest()), satisfied
    automatically by using its real loopback base_url as-is.

    Much smaller than InMySandboxRuntimeClient: InMyR&D has no
    create/stop/destroy lifecycle, just a list and a run.
    `execution_may_have_run` is set only on errors from run_experiment(),
    the one call with a real side effect (see this module's header).
    """

    def __init__(
        self,
        *,
        base_url: str,
        timeout_seconds: float = 20.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = _normalize_loopback_base_url(base_url, label='inmyrnd_base_url')
        # 20s default, not Sandbox's 305s: evaluateExperiment() is a pure,
        # synchronous, in-process computation over at most LIMITS.maxCases
        # (12) cases -- there is no real external process InMyR&D is
        # waiting on, unlike InMySandbox's up-to-300s Docker job ceiling.
        if not isinstance(timeout_seconds, (int, float)) or isinstance(timeout_seconds, bool) or not 1 <= float(timeout_seconds) <= 60:
            raise ValueError('InMyR&D client timeout must be between 1 and 60 seconds.')
        self.timeout_seconds = float(timeout_seconds)
        self.transport = transport

    async def _request(self, method: str, path: str, payload: dict[str, Any] | None, *, side_effecting: bool) -> Any:
        if method not in {'GET', 'POST'} or not path.startswith('/api/'):
            raise ValueError('InMyR&D request shape is invalid.')
        headers = {'accept': 'application/json'}
        if method == 'POST':
            headers['content-type'] = 'application/json'
        error_cls = RndExecutionError
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
                unavailable_message='InMyR&D local runtime is unavailable.',
            )
        except error_cls as exc:
            if not side_effecting:
                raise error_cls(str(exc), status_code=exc.status_code, code=exc.code, execution_may_have_run=False) from exc
            raise
        return decoded

    async def list_experiments(self) -> list[dict[str, Any]]:
        """GET /api/experiments -- InMyR&D has no single-experiment GET
        route (confirmed against the real, live server.mjs), so a caller
        that needs one experiment must fetch the full list and filter by
        id itself. Not side-effecting: a pure read.

        Note this bypasses `_bounded_json_request`'s dict-shape enforcement
        -- InMyR&D's /api/experiments returns a JSON *array*, not an
        object, unlike every other endpoint this module or
        connect_inmysandbox.py talks to. This method does its own bounded-
        size request and array-shape check rather than reusing the shared
        helper, which would reject an array response as malformed.
        """
        headers = {'accept': 'application/json'}
        timeout = httpx.Timeout(self.timeout_seconds)
        error_cls = RndExecutionError
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False, transport=self.transport) as client:
            try:
                async with client.stream('GET', f'{self.base_url}/api/experiments', headers=headers) as response:
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > _MAX_RESPONSE_BYTES:
                            raise error_cls('Response exceeded the bounded response size.', execution_may_have_run=False)
                    try:
                        decoded = json.loads(body.decode('utf-8')) if body else []
                    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, ValueError) as exc:
                        raise error_cls('Response was not valid JSON.', execution_may_have_run=False) from exc
                    if response.status_code < 200 or response.status_code >= 300:
                        message = decoded.get('error') if isinstance(decoded, dict) and isinstance(decoded.get('error'), str) else 'Request failed.'
                        raise error_cls(message, status_code=response.status_code, execution_may_have_run=False)
                    if not isinstance(decoded, list):
                        raise error_cls('Response must be a JSON array.', execution_may_have_run=False)
                    return decoded
            except error_cls:
                raise
            except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError) as exc:
                raise error_cls('InMyR&D local runtime is unavailable.', execution_may_have_run=False) from exc
            except Exception as exc:  # noqa: BLE001
                raise error_cls('Request failed unexpectedly.', execution_may_have_run=False) from exc

    async def run_experiment(self, experiment_id: str) -> dict[str, Any]:
        """POST /api/experiments/{id}/run -- reads no request body
        (confirmed against the real, live server.mjs), returns the new run
        object with HTTP 201. Side-effecting: appends a run record and
        flips the experiment's status to 'evaluated', even though the
        underlying computation is pure and deterministic.
        """
        eid = _validate_experiment_id(experiment_id)
        return await self._request('POST', f'/api/experiments/{eid}/run', {}, side_effecting=True)


def create_rnd_authority_client(
    *,
    base_url: str,
    hub_service_token: str,
    timeout_seconds: float = 20.0,
) -> RndAuthorityClient:
    return RndAuthorityClient(base_url=base_url, hub_service_token=hub_service_token, timeout_seconds=timeout_seconds)


def create_inmyrnd_runtime_client(
    *,
    base_url: str,
    timeout_seconds: float = 20.0,
) -> InMyRndRuntimeClient:
    return InMyRndRuntimeClient(base_url=base_url, timeout_seconds=timeout_seconds)
