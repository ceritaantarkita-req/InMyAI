from __future__ import annotations

"""Q8.1 -- Efficiency Router shadow telemetry.

Per docs/plans/inmy_master_roadmap_V2.md (governance repo), Part 4, Q8.1,
owner-approved 2026-08-19: this module ONLY observes and records
provider/model selection decisions that have ALREADY happened. It has
zero routing authority, today or implicitly later.

Hard invariants (do not weaken without a fresh, separately authorized
design decision -- see Part 5's D6/D7 pattern for how new capability
gets its own gate rather than inheriting an existing one):

  - Recording a telemetry entry must NEVER change, delay, or block the
    request it describes. It is called strictly after the real
    provider/model decision -- and dispatch, success or failure -- has
    already happened.
  - This module never reads its own log to influence a live decision.
    It is write-only from the request path's perspective. Nothing in
    this file contains routing logic, recommendation logic, or
    benchmark/comparison logic -- those are Q8.2 and Q8.3, separately
    scoped and explicitly not part of this file.
  - A failure to write a telemetry record must never surface as a
    user-facing error and must never fail the request it describes --
    this mirrors the existing best-effort, never-throws pattern already
    used for D3's spend counter
    (InMyHub's server/provider-execution-r1-budget.mjs).
  - This log is a derived, disposable, regeneratable-from-real-events
    observability layer. It is never a source of truth for anything
    Part 3 of the roadmap already owns (spend, receipts, authority). If
    it were lost, nothing in the live system would be affected -- that
    is a deliberate design property, not an oversight.
  - The log is LOCAL_ONLY (Part 2.6's sync-class vocabulary): it lives
    under the app's own local data_dir and is never sent anywhere. If a
    future slice wants to sync or upload it, that needs its own
    separate decision, not an implicit extension of this one.
"""

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .config import settings

logger = logging.getLogger(__name__)

TELEMETRY_SUBDIR = 'telemetry'
TELEMETRY_FILENAME = 'efficiency-router-shadow.jsonl'


@dataclass(frozen=True)
class ChatTelemetryRecord:
    """One observed chat routing/dispatch outcome. Every field describes
    something that already happened -- nothing here is a recommendation
    or a prediction."""

    request_id: str
    timestamp: str
    task_classification: str
    selection_mode: str
    provider_used: str
    model_used: str | None
    selection_reason: str
    latency_ms: int
    outcome: str
    error_class: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    cost_usd: float | None = None

    def to_json_line(self) -> str:
        return json.dumps(asdict(self), separators=(',', ':'), sort_keys=True)


def telemetry_log_path() -> Path:
    """Resolved fresh on every call, not cached at import time, so the
    test harness's per-session settings.data_dir override
    (services/api/tests/conftest.py) is honoured automatically, and a
    production data_dir change takes effect without a restart-order
    dependency."""
    return Path(settings.data_dir) / TELEMETRY_SUBDIR / TELEMETRY_FILENAME


def record_chat_telemetry(record: ChatTelemetryRecord) -> None:
    """Append one shadow-telemetry line. Best-effort: any failure here is
    logged and swallowed, never raised, so a telemetry problem can never
    turn into a chat-request failure. A lost record is an acceptable
    trade-off; a broken chat response is not -- see the module
    docstring's invariants."""
    try:
        path = telemetry_log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('a', encoding='utf-8') as handle:
            handle.write(record.to_json_line())
            handle.write('\n')
    except Exception:  # noqa: BLE001 -- deliberately broad, see docstring
        logger.warning('efficiency_router_telemetry: failed to record entry (non-fatal)', exc_info=True)


def build_chat_telemetry_record(
    *,
    request_id: str,
    timestamp: str,
    task: str,
    selection_mode: str,
    provider_used: str,
    model_used: str | None,
    selection_reason: str,
    latency_ms: int,
    outcome: str,
    error_class: str | None = None,
    usage: dict[str, Any] | None = None,
) -> ChatTelemetryRecord:
    """Pure helper: turns already-known values into a record. No
    guessing and no default that implies a decision -- every value must
    be supplied by the caller from data it already computed for the
    real response.

    `usage` is expected in the shape InMyConnect's governed OpenRouter
    receipt already uses (see docs/phase5-q6-bounded-e2e-acceptance-v1.md
    for a real example): promptTokens/completionTokens/totalTokens/cost.
    Local (Ollama/mock) calls have no such usage object, so every numeric
    field below is simply None for those -- not zero, which would falsely
    imply a measured-and-free result rather than an unmeasured one.
    """
    prompt_tokens = completion_tokens = total_tokens = None
    cost_usd = None
    if isinstance(usage, dict):
        prompt_tokens = usage.get('promptTokens')
        completion_tokens = usage.get('completionTokens')
        total_tokens = usage.get('totalTokens')
        cost_usd = usage.get('cost')
    return ChatTelemetryRecord(
        request_id=request_id,
        timestamp=timestamp,
        task_classification=task,
        selection_mode=selection_mode,
        provider_used=provider_used,
        model_used=model_used,
        selection_reason=selection_reason,
        latency_ms=latency_ms,
        outcome=outcome,
        error_class=error_class,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        cost_usd=cost_usd,
    )
