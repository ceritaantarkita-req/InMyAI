from __future__ import annotations

import codecs
import inspect
import ipaddress
import json
import re
import time
import warnings
from typing import Any, Callable
from urllib.parse import urlparse

import httpx


_MAX_RESPONSE_BYTES = 2 * 1024 * 1024

# Streaming bounds. These deliberately mirror the ones InMyConnect's stream
# adapter enforces on the OpenRouter side (Q10.8 slice 2). The bridge is
# local and is the component trusted to hold the API key, but it is still a
# separate process that can be restarted, upgraded, or wedged independently
# of this one, so this client bounds what it will accept rather than
# assuming the far end already did.
#
# Two time bounds are needed, not one. The total-duration deadline bounds a
# stream that trickles forever; httpx's read timeout bounds a stream that
# goes silent while the socket stays open. A deadline alone cannot catch the
# second case, because a coroutine awaiting a read that never resolves never
# gets back to the loop to check the clock.
_MAX_STREAM_RESPONSE_BYTES = 2 * 1024 * 1024
_MAX_STREAM_DURATION_SECONDS = 300.0
_MAX_SSE_EVENT_BYTES = 256 * 1024
_MAX_ERROR_BODY_BYTES = 64 * 1024
_SAFE_ERROR_CODE = re.compile(r'^[A-Z0-9_:-]{2,128}$')

_CONNECTION_ID = re.compile(r'^conn_[A-Za-z0-9_-]{16,96}$')
_MODEL_ID = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._:/~-]{0,191}$')
_IDEMPOTENCY_KEY = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._:/-]{7,255}$')


class ConnectOpenRouterError(RuntimeError):
    """A failure at the InMyConnect boundary.

    `receipt_may_exist` is the money-relevant flag, and it is deliberately
    NOT derivable from `code`. It is True when the failure happened after
    InMyConnect committed to an HTTP 200 on a streamed call, because from
    that point on the bridge may already have run a real execution and
    recorded a real receipt that simply never reached this process.

    A caller must never retry such a call under a NEW idempotency key: the
    execution may already have been paid for, and a new key pays again.
    Reuse the same key so the replay path returns the original receipt, or
    go through recovery. Branch on this flag, not on the code string.
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int = 503,
        code: str = 'CONNECT_OPENROUTER_ERROR',
        receipt_may_exist: bool = False,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.receipt_may_exist = receipt_may_exist


def _bounded_string(value: Any, label: str, *, minimum: int = 1, maximum: int = 4096) -> str:
    if not isinstance(value, str) or not minimum <= len(value) <= maximum or '\x00' in value:
        raise ValueError(f'{label} must be a bounded NUL-free string.')
    if value.strip() != value:
        raise ValueError(f'{label} cannot have surrounding whitespace.')
    return value


def _normalize_loopback_base_url(value: str) -> str:
    raw = _bounded_string(value, 'connect_base_url', minimum=8, maximum=256)
    parsed = urlparse(raw)
    if parsed.scheme != 'http':
        raise ValueError('InMyConnect base URL must use plain HTTP on loopback.')
    if parsed.username or parsed.password:
        raise ValueError('InMyConnect base URL cannot contain credentials.')
    if parsed.query or parsed.fragment or parsed.path not in ('', '/'):
        raise ValueError('InMyConnect base URL cannot contain path, query, or fragment data.')
    if parsed.port is None:
        raise ValueError('InMyConnect base URL must include an explicit port.')
    try:
        address = ipaddress.ip_address(parsed.hostname or '')
    except ValueError as exc:
        raise ValueError('InMyConnect base URL must use an explicit loopback IP literal.') from exc
    if not address.is_loopback:
        raise ValueError('InMyConnect base URL must be loopback-only.')
    host = f'[{address.compressed}]' if address.version == 6 else address.compressed
    return f'http://{host}:{parsed.port}'


def _normalize_bearer_token(value: str) -> str:
    token = _bounded_string(value, 'Hub service token', minimum=16, maximum=8192)
    if re.search(r'\s', token):
        raise ValueError('Hub service token is malformed.')
    return token


def _validate_connection_id(value: str) -> str:
    candidate = _bounded_string(value, 'connection_id', maximum=101)
    if not _CONNECTION_ID.fullmatch(candidate):
        raise ValueError('connection_id is invalid.')
    return candidate


def _validate_model_id(value: str) -> str:
    candidate = _bounded_string(value, 'model_id', maximum=192)
    if not _MODEL_ID.fullmatch(candidate):
        raise ValueError('model_id is invalid.')
    return candidate


def _validate_idempotency_key(value: str) -> str:
    candidate = _bounded_string(value, 'idempotency_key', minimum=8, maximum=256)
    if not _IDEMPOTENCY_KEY.fullmatch(candidate):
        raise ValueError('idempotency_key is invalid.')
    return candidate


class ConnectOpenRouterClient:
    """Server-side client for the local InMyConnect OpenRouter bridge.

    This object never talks to OpenRouter directly. The Bearer credential is
    the InMyHub service identity for agent:inmyai and is only forwarded to the
    local Connect boundary. The OpenRouter API key remains inside InMyConnect.
    """

    def __init__(
        self,
        *,
        base_url: str,
        hub_service_token: str,
        timeout_seconds: float = 20.0,
        stream_idle_timeout_seconds: float = 60.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = _normalize_loopback_base_url(base_url)
        self._token = _normalize_bearer_token(hub_service_token)
        if not isinstance(timeout_seconds, (int, float)) or isinstance(timeout_seconds, bool) or not 1 <= float(timeout_seconds) <= 60:
            raise ValueError('connect timeout must be between 1 and 60 seconds.')
        self.timeout_seconds = float(timeout_seconds)
        # Separate from timeout_seconds on purpose. This bounds silence
        # BETWEEN stream frames, and time-to-first-token on a large model
        # can legitimately exceed a timeout sized for a buffered request --
        # tripping it would destroy an already-billed generation.
        if (
            not isinstance(stream_idle_timeout_seconds, (int, float))
            or isinstance(stream_idle_timeout_seconds, bool)
            or not 5 <= float(stream_idle_timeout_seconds) <= 300
        ):
            raise ValueError('stream idle timeout must be between 5 and 300 seconds.')
        self.stream_idle_timeout_seconds = float(stream_idle_timeout_seconds)
        self.transport = transport

    async def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        if method not in {'GET', 'POST'} or not path.startswith('/api/openrouter/'):
            raise ValueError('InMyConnect OpenRouter request shape is invalid.')
        headers = {
            'accept': 'application/json',
            'authorization': f'Bearer {self._token}',
        }
        if method == 'POST':
            headers['content-type'] = 'application/json'

        timeout = httpx.Timeout(self.timeout_seconds)
        # Once the bridge answers 2xx it has already run the execution, so a
        # failure while reading the body is a failure that may have spent
        # money -- the same invariant the streamed path enforces. Tracked
        # here so the flag cannot be forgotten on the buffered path, which
        # is the one in production use today.
        committed = False
        async with httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=False,
            transport=self.transport,
        ) as client:
            try:
                async with client.stream(
                    method,
                    f'{self.base_url}{path}',
                    headers=headers,
                    json=payload if method == 'POST' else None,
                ) as response:
                    committed = 200 <= response.status_code < 300
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > _MAX_RESPONSE_BYTES:
                            raise ConnectOpenRouterError(
                                'InMyConnect response exceeded the bounded response size.',
                                receipt_may_exist=committed,
                            )
                    try:
                        decoded = json.loads(body.decode('utf-8')) if body else {}
                    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, ValueError) as exc:
                        raise ConnectOpenRouterError(
                            'InMyConnect returned invalid JSON.',
                            receipt_may_exist=committed,
                        ) from exc
                    if not isinstance(decoded, dict):
                        raise ConnectOpenRouterError(
                            'InMyConnect response must be a JSON object.',
                            receipt_may_exist=committed,
                        )
                    if response.status_code < 200 or response.status_code >= 300:
                        code = decoded.get('code') if isinstance(decoded.get('code'), str) else 'CONNECT_HTTP_ERROR'
                        safe_code = code if re.fullmatch(r'[A-Z0-9_:-]{2,128}', code) else 'CONNECT_HTTP_ERROR'
                        raise ConnectOpenRouterError(
                            f'InMyConnect request failed with status {response.status_code} ({safe_code}).',
                            status_code=response.status_code,
                            code=safe_code,
                        )
                    return decoded
            except ConnectOpenRouterError:
                raise
            except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError) as exc:
                raise ConnectOpenRouterError(
                    'InMyConnect local runtime is unavailable.',
                    receipt_may_exist=committed,
                ) from exc
            except Exception as exc:  # noqa: BLE001
                # Same principle as the streamed path: an exception this
                # module never anticipated (a mislabelled content-encoding
                # raising httpx.DecodingError, say) is exactly when a caller
                # most needs to know whether money may already have moved.
                raise ConnectOpenRouterError(
                    'InMyConnect request failed unexpectedly.',
                    receipt_may_exist=committed,
                ) from exc

    async def status(self) -> dict[str, Any]:
        return await self._request('GET', '/api/openrouter/status')

    async def list_models(self, *, connection_id: str, idempotency_key: str) -> dict[str, Any]:
        return await self._request('POST', '/api/openrouter/models', {
            'connectionId': _validate_connection_id(connection_id),
            'idempotencyKey': _validate_idempotency_key(idempotency_key),
        })

    async def chat(
        self,
        *,
        workflow_run_id: str,
        delegation_id: str,
        connection_id: str,
        model_id: str,
        idempotency_key: str,
        input_sensitivity: str,
        requested_output_tokens: int,
        messages: list[dict[str, str]],
    ) -> dict[str, Any]:
        return await self._request('POST', '/api/openrouter/chat', _build_chat_payload(
            workflow_run_id=workflow_run_id,
            delegation_id=delegation_id,
            connection_id=connection_id,
            model_id=model_id,
            idempotency_key=idempotency_key,
            input_sensitivity=input_sensitivity,
            requested_output_tokens=requested_output_tokens,
            messages=messages,
        ))

    async def chat_stream(
        self,
        *,
        workflow_run_id: str,
        delegation_id: str,
        connection_id: str,
        model_id: str,
        idempotency_key: str,
        input_sensitivity: str,
        requested_output_tokens: int,
        messages: list[dict[str, str]],
        on_chunk: Callable[[str], Any] | None = None,
    ) -> dict[str, Any]:
        """Run one governed chat over the bridge's SSE route.

        The return value is the same governed result `chat()` returns, so a
        caller that does not care about tokens arriving early can swap one
        for the other and read the receipt exactly the same way. `on_chunk`,
        when given, is called with each text delta as it arrives.

        Four properties are deliberate, and each mirrors a decision already
        reviewed on the InMyConnect side:

        1. **Returning means the bridge reached a governed outcome.** For an
           authorized call that outcome carries a receipt -- including a
           stream that broke after real tokens, which InMyConnect records as
           `outcome: 'partial'` and delivers in the terminal event, so this
           method returns it rather than raising and spend is not lost. A
           Hub *denial* is also a governed outcome and is returned untouched
           with `authorized: false` and no receipt; the caller decides.

        2. **A terminal event already in hand always beats a bound.** Every
           bound is checked only after the bytes just read have been parsed.
           A deadline or size cap that fires on the very read carrying the
           receipt would throw away spend that was already incurred, which
           is the exact failure the bounds exist to prevent.

        3. **A consumer that throws never destroys an already-billed
           generation.** If `on_chunk` raises, the exception is swallowed
           and the stream keeps going. The generation is already paid for;
           a rendering bug must not turn it into a failure with no receipt.

        4. **Every failure this method RAISES after HTTP 200 is marked
           `receipt_may_exist`.** Once the bridge commits to 200 it may
           already have run, and recorded, a real execution. Such a call must
           NOT be retried under a *new* idempotency key -- that pays twice.
           Reuse the same key, or go through the recovery path. Callers
           branch on `error.receipt_may_exist`, never on the specific code.

           Two limits are stated rather than papered over. **Cancellation**
           does not carry the flag: `asyncio.wait_for` discards the inner
           exception and raises its own `TimeoutError`, so no attribute
           survives. Treat cancelling a `chat_stream` that has already
           started as receipt-may-exist. And a **chained** exception's
           `__cause__` still holds the raw event text (and, on the buffered
           path, request headers) -- invisible to normal traceback
           rendering, but an error tracker that serializes exception
           attributes or frame locals would see it.
        """
        _validate_on_chunk(on_chunk)
        payload = _build_chat_payload(
            workflow_run_id=workflow_run_id,
            delegation_id=delegation_id,
            connection_id=connection_id,
            model_id=model_id,
            idempotency_key=idempotency_key,
            input_sensitivity=input_sensitivity,
            requested_output_tokens=requested_output_tokens,
            messages=messages,
        )

        headers = {
            'accept': 'text/event-stream',
            'authorization': f'Bearer {self._token}',
            'content-type': 'application/json',
        }
        # read=stream_idle_timeout_seconds bounds silence BETWEEN frames;
        # the deadline set below bounds the stream as a whole. The idle
        # bound is separate from timeout_seconds because time-to-first-token
        # on a large model can exceed a request timeout sized for a buffered
        # call, and tripping it would destroy a billed generation.
        timeout = httpx.Timeout(self.timeout_seconds, read=self.stream_idle_timeout_seconds)

        # Tracks the commit point. Before it, a failure means nothing ran and
        # retrying under a fresh idempotency key is safe. After it, the
        # bridge may already have run and recorded a real execution.
        committed = False
        async with httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=False,
            transport=self.transport,
        ) as client:
            try:
                async with client.stream(
                    'POST',
                    f'{self.base_url}/api/openrouter/chat/stream',
                    headers=headers,
                    json=payload,
                ) as response:
                    if response.status_code < 200 or response.status_code >= 300:
                        # A failure before the stream opens is an ordinary
                        # HTTP error with a real status: nothing ran, so
                        # there is no receipt and no spend.
                        raise await self._stream_precommit_error(response)
                    committed = True

                    # From here on the bridge has committed to 200 and may
                    # have run a real, recorded execution. EVERY exit below
                    # goes through _stream_failure, including exceptions
                    # this module did not anticipate -- an unexpected error
                    # after the commit point is precisely when a caller most
                    # needs to know not to retry under a fresh key.
                    try:
                        return await self._consume_stream(response, on_chunk)
                    except ConnectOpenRouterError:
                        raise
                    except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError) as exc:
                        raise _stream_failure(
                            'InMyConnect stream ended before the terminal event; '
                            'a receipt may exist that did not reach this client.',
                            'CONNECT_STREAM_INCOMPLETE',
                        ) from exc
                    except Exception as exc:  # noqa: BLE001 - see comment above
                        raise _stream_failure(
                            'InMyConnect stream failed after the response was committed; '
                            'a receipt may exist that did not reach this client.',
                            'CONNECT_STREAM_FAILED',
                        ) from exc
            except ConnectOpenRouterError:
                raise
            except Exception as exc:  # noqa: BLE001
                # Opening the stream, or closing it, can fail outside the
                # block above -- most commonly because the local bridge is
                # simply not running. `chat()` converts every such failure;
                # this path used to let raw httpx exceptions escape, so a
                # caller doing `except ConnectOpenRouterError` did not catch
                # its most likely failure at all.
                raise ConnectOpenRouterError(
                    'InMyConnect local runtime is unavailable.',
                    code='CONNECT_STREAM_INCOMPLETE' if committed else 'CONNECT_OPENROUTER_ERROR',
                    receipt_may_exist=committed,
                ) from exc

    async def _consume_stream(
        self,
        response: httpx.Response,
        on_chunk: Callable[[str], Any] | None,
    ) -> dict[str, Any]:
        content_type = (response.headers.get('content-type') or '').split(';')[0].strip().lower()
        if content_type != 'text/event-stream':
            raise _stream_failure(
                'InMyConnect stream response was not an event stream.',
                'CONNECT_STREAM_INVALID',
            )

        # Started only now: connect time and time-to-first-byte are not
        # charged against the generation's own budget.
        deadline = time.monotonic() + _MAX_STREAM_DURATION_SECONDS
        # utf-8-sig, and incremental: a byte-order mark would otherwise glue
        # itself to the first field name and silently demote the first event
        # to an ignored unknown one, and a multi-byte character split across
        # a socket read is ordinary and must not fail a paid generation.
        decoder = codecs.getincrementaldecoder('utf-8-sig')()
        state = _StreamState(on_chunk)
        total = 0

        async for raw in response.aiter_bytes():
            total += len(raw)
            try:
                state.feed(decoder.decode(raw))
            except UnicodeDecodeError as exc:
                raise _stream_failure(
                    'InMyConnect stream contained undecodable bytes.',
                    'CONNECT_STREAM_INVALID',
                ) from exc

            result = state.drain()
            # Property 2: the terminal event wins over every bound below,
            # because the spend already happened.
            if result is not None:
                return result
            if total > _MAX_STREAM_RESPONSE_BYTES:
                raise _stream_failure(
                    'InMyConnect stream exceeded the bounded response size.',
                    'CONNECT_STREAM_TOO_LARGE',
                )
            if time.monotonic() > deadline:
                raise _stream_failure(
                    'InMyConnect stream exceeded its wall-clock bound.',
                    'CONNECT_STREAM_TIMEOUT',
                )
            state.check_pending_frame_bound()

        # End of stream. Flush whatever the decoder and the CR hold-back are
        # still sitting on, then drain once more: a terminal event that is
        # fully on the wire must not be discarded just because the stream's
        # last byte happened to be a bare CR, or a trailing partial
        # character never arrived.
        try:
            state.feed(decoder.decode(b'', final=True))
        except UnicodeDecodeError:
            pass
        result = state.drain(final=True)
        if result is not None:
            return result
        raise _stream_failure(
            'InMyConnect stream ended before the terminal event; '
            'a receipt may exist that did not reach this client.',
            'CONNECT_STREAM_INCOMPLETE',
        )

    async def _stream_precommit_error(self, response: httpx.Response) -> ConnectOpenRouterError:
        body = bytearray()
        try:
            async for part in response.aiter_bytes():
                body.extend(part)
                if len(body) > _MAX_ERROR_BODY_BYTES:
                    break
        except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError):
            body = bytearray()
        code = 'CONNECT_HTTP_ERROR'
        try:
            decoded = json.loads(bytes(body).decode('utf-8')) if body else {}
            candidate = decoded.get('code') if isinstance(decoded, dict) else None
            if isinstance(candidate, str) and _SAFE_ERROR_CODE.fullmatch(candidate):
                code = candidate
        except (UnicodeDecodeError, json.JSONDecodeError):
            pass
        return ConnectOpenRouterError(
            f'InMyConnect stream request failed with status {response.status_code} ({code}).',
            status_code=response.status_code,
            code=code,
        )


def _stream_failure(message: str, code: str) -> ConnectOpenRouterError:
    """Every post-commit stream failure goes through here.

    One place, so the receipt_may_exist flag cannot be forgotten on a new
    branch: past HTTP 200, the bridge may already have recorded spend.
    """
    return ConnectOpenRouterError(message, status_code=502, code=code, receipt_may_exist=True)


def _validate_on_chunk(on_chunk: Callable[[str], Any] | None) -> None:
    """Reject a consumer that cannot possibly receive deltas.

    An un-awaited coroutine is discarded silently, so an async consumer
    would hand the caller a perfect receipt and zero tokens with no trace.
    Both static shapes are caught here -- `async def`, and an object whose
    `__call__` is async. A plain function that merely *returns* a coroutine
    cannot be detected until it is called; `_StreamState` handles that one
    at call time, because by then a generation is already being paid for
    and refusing it would cost more than it saves.
    """
    if on_chunk is None:
        return
    if not callable(on_chunk):
        raise ValueError('on_chunk must be callable or omitted.')
    if inspect.iscoroutinefunction(on_chunk) or inspect.iscoroutinefunction(
        getattr(on_chunk, '__call__', None)
    ):
        raise ValueError('on_chunk must be a plain callable, not a coroutine function.')


class _StreamState:
    """Buffer, frame, and dispatch one SSE stream.

    Split out of `chat_stream` so end-of-stream can run the same draining
    logic the read loop runs -- round 2 found that a stream whose last byte
    is a bare CR otherwise had its fully-received terminal event discarded.
    """

    __slots__ = ('_buffer', '_scan_from', '_on_chunk', '_on_chunk_disabled')

    def __init__(self, on_chunk: Callable[[str], Any] | None) -> None:
        self._buffer = ''
        # Where to resume the delimiter search. Without it every read
        # rescans the whole pending buffer, which is quadratic in the number
        # of reads -- measured at ~15x CPU for one request when a bridge
        # flushes per token. Bounded, but wasteful for no reason.
        self._scan_from = 0
        self._on_chunk = on_chunk
        self._on_chunk_disabled = False

    def feed(self, text: str) -> None:
        if not text:
            return
        # Normalize CR/CRLF, but never in a way that can split an event at a
        # read boundary: a lone trailing CR may be the first half of a CRLF
        # whose LF has not arrived. Rewriting it now would manufacture a
        # spurious blank line -- an SSE event delimiter -- in the middle of
        # an event, silently cutting a terminal `done` in half. So it is
        # held back untouched and normalized once more bytes arrive, or at
        # end of stream by drain(final=True).
        # Where a delimiter could newly appear. Normalizing can COLLAPSE a
        # CRLF that straddles the join, shifting everything after it one
        # character left -- so a resume offset taken from the old length can
        # step over a delimiter that just formed. Backing off two characters
        # covers both that shift and the fact that a delimiter spans two
        # characters. Round 2 found the un-backed-off version silently
        # skipping the terminal event on a CR-framed byte-at-a-time stream.
        safe_resume = max(0, len(self._buffer) - 2)
        self._buffer += text
        held = self._buffer.endswith('\r')
        body = self._buffer[:-1] if held else self._buffer
        self._buffer = body.replace('\r\n', '\n').replace('\r', '\n') + ('\r' if held else '')
        self._scan_from = min(self._scan_from, safe_resume)

    def drain(self, *, final: bool = False) -> dict[str, Any] | None:
        if final and self._buffer.endswith('\r'):
            # No further bytes are coming, so the held-back CR is a real
            # line terminator after all. Backing the resume offset off by
            # one matters: the delimiter this creates ends at the last
            # character, and a resume offset parked there would miss it.
            self._buffer = self._buffer[:-1] + '\n'
            self._scan_from = max(0, self._scan_from - 1)
        oversized = False
        while True:
            index = self._buffer.find('\n\n', self._scan_from)
            if index < 0:
                # A delimiter spans two characters, so resume one short of
                # the end rather than at it.
                self._scan_from = max(0, len(self._buffer) - 1)
                break
            block = self._buffer[:index]
            self._buffer = self._buffer[index + 2:]
            self._scan_from = 0
            if _over_frame_bound(block):
                # Skipped, not raised on the spot. By the time an oversized
                # block is delimited its memory is already allocated, so
                # rejecting immediately saves nothing -- and it would throw
                # away a terminal receipt sitting right behind it, which is
                # the one thing the bounds exist to protect. Unbounded growth
                # of UNDELIMITED data, the case the bound actually guards, is
                # still caught by check_pending_frame_bound between reads.
                oversized = True
                continue
            result = self._dispatch(block)
            if result is not None:
                return result
        if oversized:
            raise _stream_failure(
                'InMyConnect stream sent an oversized frame.',
                'CONNECT_STREAM_TOO_LARGE',
            )
        return None

    def check_pending_frame_bound(self) -> None:
        # No delimiter has arrived within one event's worth of data.
        #
        # Characters, not bytes, and deliberately so: a UTF-8 character is
        # never smaller than one byte, so char-count > bound PROVES
        # byte-count > bound -- exact in the only direction that rejects.
        # The reverse slack is bounded by the total-bytes cap. Re-encoding
        # the whole pending buffer on every read instead costs ~12s of CPU
        # against a bridge that dribbles a delimiter-less frame one byte at
        # a time, for no added safety.
        if len(self._buffer) > _MAX_SSE_EVENT_BYTES:
            raise _stream_failure(
                'InMyConnect stream sent an oversized frame.',
                'CONNECT_STREAM_TOO_LARGE',
            )

    def _dispatch(self, block: str) -> dict[str, Any] | None:
        name, data = _parse_sse_block(block)
        if name is None:
            return None
        if name == 'chunk':
            text = _sse_json(data).get('text')
            if isinstance(text, str) and text:
                self._emit(text)
            return None
        if name == 'done':
            return _validated_terminal_result(_sse_json(data))
        if name == 'error':
            # receipt_may_exist is unconditionally True here, not inferred
            # from whether this client happened to see a content delta.
            # InMyConnect bills on evidence this client never sees --
            # reasoning tokens, tool-call deltas, a usage frame that arrived
            # before any content -- so "I saw no text" is not "no money
            # moved". The safe direction is to assume it did.
            raise _stream_error_event(_sse_json(data))
        # Unknown event names are ignored on purpose, so a newer bridge can
        # add events without breaking an older client.
        return None

    def _emit(self, text: str) -> None:
        if self._on_chunk is None or self._on_chunk_disabled:
            return
        try:
            returned = self._on_chunk(text)
        except Exception:  # noqa: BLE001 - property 3: never lose a paid generation
            return
        if inspect.isawaitable(returned) or inspect.isasyncgen(returned):
            # A sync wrapper around an async consumer. Deltas cannot be
            # delivered, but the generation is already being paid for, so
            # this warns loudly and keeps the receipt rather than raising.
            self._on_chunk_disabled = True
            closer = getattr(returned, 'close', None)
            if callable(closer):
                closer()
            warnings.warn(
                'on_chunk returned an awaitable; deltas cannot be delivered to an '
                'async consumer and will be dropped for the rest of this stream.',
                RuntimeWarning,
                stacklevel=2,
            )


def _over_frame_bound(text: str) -> bool:
    """Is this frame over the bound, measured in BYTES as its name says?

    `len()` counts characters, and this stream carries unescaped multi-byte
    UTF-8 from a Node bridge, so a character count alone would allow up to
    4x the declared bound. Encoding every frame just to measure it would be
    wasteful, so the cheap character check gates the exact one: below a
    quarter of the bound no string can exceed it.
    """
    if len(text) <= _MAX_SSE_EVENT_BYTES // 4:
        return False
    return len(text.encode('utf-8', 'surrogatepass')) > _MAX_SSE_EVENT_BYTES


def _validated_terminal_result(payload: dict[str, Any]) -> dict[str, Any]:
    """Reject a terminal `done` event that carries no governed outcome.

    "Returning means a receipt exists" is this method's headline guarantee,
    so it is checked rather than assumed. A wedged or half-upgraded bridge
    emitting a bare `done` would otherwise read as a clean success with no
    spend record at all. `authorized: false` IS a legitimate governed
    outcome (the Hub denied the call) and is passed through untouched --
    the caller decides what to do with a denial.
    """
    if not isinstance(payload.get('authorized'), bool):
        raise _stream_failure(
            'InMyConnect stream terminated without a governed authorization outcome.',
            'CONNECT_STREAM_INVALID',
        )
    if payload['authorized'] and not isinstance(payload.get('receipt'), dict):
        raise _stream_failure(
            'InMyConnect stream terminated without an execution receipt.',
            'CONNECT_STREAM_INVALID',
        )
    return payload


def _parse_sse_block(block: str) -> tuple[str | None, str]:
    """Parse one SSE event block into (event name, data payload).

    Returns (None, '') for a block that carries no data -- notably
    OpenRouter-style keep-alive comment lines, which InMyConnect may pass
    through and which must never be mistaken for content. Multiple `data:`
    lines are joined with newlines, per the SSE spec, rather than assuming
    the bridge only ever writes one.
    """
    name: str | None = None
    data_lines: list[str] = []
    for line in block.split('\n'):
        if not line or line.startswith(':'):
            continue
        field, _, value = line.partition(':')
        if value.startswith(' '):
            value = value[1:]
        if field == 'event':
            name = value
        elif field == 'data':
            data_lines.append(value)
    if not data_lines:
        return None, ''
    return (name or 'message'), '\n'.join(data_lines)


def _sse_json(data: str) -> dict[str, Any]:
    try:
        decoded = json.loads(data)
    except (json.JSONDecodeError, RecursionError, ValueError) as exc:
        raise _stream_failure(
            'InMyConnect stream sent a malformed event.',
            'CONNECT_STREAM_INVALID',
        ) from exc
    if not isinstance(decoded, dict):
        raise _stream_failure(
            'InMyConnect stream event must be a JSON object.',
            'CONNECT_STREAM_INVALID',
        )
    return decoded


def _stream_error_event(payload: dict[str, Any]) -> ConnectOpenRouterError:
    """Turn a terminal SSE error event into a sanitized exception.

    Only the code crosses over, and only if it matches the closed shape the
    bridge is supposed to emit. The message is composed here rather than
    forwarded: once a stream has committed to HTTP 200, an attacker-shaped
    or upstream-shaped `message` field is the one remaining way raw provider
    text could reach a caller, and through it a log or a UI.

    receipt_may_exist is unconditionally True. An error event can only
    arrive after the bridge committed to HTTP 200, and InMyConnect bills on
    evidence this client never sees -- reasoning tokens, tool-call deltas, a
    usage frame that arrived before any content. Inferring the flag from
    whether a text delta happened to reach here would be narrower than the
    thing it claims to describe, in the direction that costs money.
    """
    candidate = payload.get('code')
    code = candidate if isinstance(candidate, str) and _SAFE_ERROR_CODE.fullmatch(candidate) else 'CONNECT_STREAM_FAILED'
    return ConnectOpenRouterError(
        f'InMyConnect reported a mid-stream failure ({code}).',
        status_code=502,
        code=code,
        receipt_may_exist=True,
    )


def _build_chat_payload(
    *,
    workflow_run_id: str,
    delegation_id: str,
    connection_id: str,
    model_id: str,
    idempotency_key: str,
    input_sensitivity: str,
    requested_output_tokens: int,
    messages: list[dict[str, str]],
) -> dict[str, Any]:
    """Validate and shape one governed chat request body.

    Shared by the buffered and streamed paths on purpose: the two must not
    be able to drift into accepting different inputs, because the Hub
    authorizes against exactly these fields.
    """
    workflow = _bounded_string(workflow_run_id, 'workflow_run_id', minimum=3, maximum=128)
    delegation = _bounded_string(delegation_id, 'delegation_id', minimum=3, maximum=128)
    connection = _validate_connection_id(connection_id)
    model = _validate_model_id(model_id)
    idem = _validate_idempotency_key(idempotency_key)
    if input_sensitivity not in {'PUBLIC', 'INTERNAL'}:
        raise ValueError('input_sensitivity must be PUBLIC or INTERNAL.')
    if isinstance(requested_output_tokens, bool) or not isinstance(requested_output_tokens, int) or not 1 <= requested_output_tokens <= 8192:
        raise ValueError('requested_output_tokens must be between 1 and 8192.')
    if not isinstance(messages, list) or not 1 <= len(messages) <= 128:
        raise ValueError('messages must contain 1..128 items.')
    normalized_messages: list[dict[str, str]] = []
    total_chars = 0
    for index, message in enumerate(messages):
        if not isinstance(message, dict) or set(message) != {'role', 'content'}:
            raise ValueError(f'messages[{index}] must contain exactly role and content.')
        role = message.get('role')
        content = message.get('content')
        if role not in {'system', 'user', 'assistant'}:
            raise ValueError(f'messages[{index}].role is unsupported.')
        text = _bounded_string(content, f'messages[{index}].content', maximum=131072)
        total_chars += len(text)
        if total_chars > 131072:
            raise ValueError('messages total content exceeds 131072 characters.')
        normalized_messages.append({'role': role, 'content': text})

    return {
        'workflowRunId': workflow,
        'delegationId': delegation,
        'connectionId': connection,
        'modelId': model,
        'idempotencyKey': idem,
        'inputSensitivity': input_sensitivity,
        'requestedOutputTokens': requested_output_tokens,
        'inputs': {'messages': normalized_messages},
    }


def create_connect_openrouter_client(
    *,
    base_url: str,
    hub_service_token: str,
    timeout_seconds: float = 20.0,
    stream_idle_timeout_seconds: float = 60.0,
) -> ConnectOpenRouterClient:
    return ConnectOpenRouterClient(
        base_url=base_url,
        hub_service_token=hub_service_token,
        timeout_seconds=timeout_seconds,
        stream_idle_timeout_seconds=stream_idle_timeout_seconds,
    )
