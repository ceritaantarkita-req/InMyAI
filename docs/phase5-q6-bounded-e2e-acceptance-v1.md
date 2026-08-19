# Phase 5 Step 6-8 (Q6) — Bounded Real E2E Acceptance Record

**Date:** 2026-08-18/19
**Status:** Q6.1-Q6.10 and Q6.12 CLOSED with evidence below. Q6.11 PARTIALLY closed — token usage and real cost are demonstrated; timeout and crash-mid-execution replay behaviour are deliberately NOT forced live (see "Explicitly out of scope" below) and remain covered only at the automated unit-test level in `InMyConnect_Foundation__main/tests/`.
**Repository this record lives in:** InMyAI (`InMyAI_FullStack__main`), because the run itself targeted InMyConnect's real bridge/Hub/OpenRouter chain that InMyAI's own composer calls — same pattern as `docs/phase5-openrouter-live-e2e-acceptance-v1.md`.
**Tracked against:** `docs/plans/inmy_master_roadmap_V2.md`, Part 4, Q6 (governance repo `ceritaantarkita-req/inmy`).

## Why this exists

The composer-wiring live E2E testing recorded in `docs/phase5-openrouter-live-e2e-acceptance-v1.md` proved the OpenRouter governed path works end-to-end for a real user, and caught a real bug (trailing-whitespace validation) along the way. That testing was organic and repeated with varying inputs — valuable, but not what Q6 asks for: **one bounded, controlled, fully-specified run**, plus explicit verification of each of Q6.5 through Q6.11's governance properties against the real request/response, not just "it seemed to work."

This record supplies that missing formal protocol and its actual results.

## Design decision: direct call to the InMyConnect bridge, not the InMyAI composer UI

The bounded run was made as a direct HTTP call to InMyConnect's own `POST /api/openrouter/chat` (the same route InMyAI's backend calls), rather than through the InMyAI chat UI. Reasons:

- The composer prepends a variable-length project-context system message to every user message — a direct call lets the prompt be fully fixed and exact.
- The composer always sends `requested_output_tokens: 1024` and `input_sensitivity: 'INTERNAL'` (Python `ChatRequest` defaults, never overridden by the UI) — a direct call is the only way to exercise a small bounded token count and the `PUBLIC` sensitivity value.
- The composer mints a fresh idempotency key on every send — a direct call is the only way to replay an *identical* request, which Q6.8 requires.
- InMyAI's own backend adds no governance logic of its own on this path; it is a byte-for-byte field pass-through to the same bridge route. Calling the bridge directly exercises exactly the same InMyConnect + InMyHub + real OpenRouter chain as the UI would, for the purposes of every property Q6.5-Q6.11 ask about.

This does not replace or invalidate the earlier UI-driven evidence; it is additional, more precisely controlled evidence for the specific governance properties Q6 requires.

## Fixed parameters used

| Parameter | Value |
|---|---|
| Endpoint | `POST http://127.0.0.1:8766/api/openrouter/chat` |
| `modelId` | `google/gemini-3.7-flash` (pinned per Q6.1, no fallback chain) |
| `requestedOutputTokens` | `32` |
| `inputSensitivity` | `PUBLIC` |
| `temperature` | `0` |
| `workflowRunId` | `q6-2-bounded-acceptance-2026-08-18` |
| `delegationId` | `inmyai-chat-q6-bounded-2026-08-18` |
| `idempotencyKey` (original + replay) | `q6.2-bounded-run-20260818-001` |
| `idempotencyKey` (Q6.9 negative test) | `q6.9-hub-down-20260818-001` |
| `connectionId` | `conn_openrouter000000` (the fixed foundation connection id printed by InMyConnect's own startup log) |
| Prompt | system: "You are a bounded test harness responder. Follow the instruction exactly and output nothing else." / user: "Reply with exactly one word and nothing else. The word is: INMYQ6BOUNDED" |
| Client timeout | 40s (server-side hard timeout is 30s, confirmed in source: `providerTimeoutMs` default in `connect-openrouter-governed-runtime.mjs`, matched by `providers/openrouter.mjs`'s adapter timeout and the bridge's own `DEFAULT_REQUEST_TIMEOUT_MS`) |
| Executed by | Repository owner, on her own machine, in her own terminal, after explicit confirmation (Q6.3) |

## Q6.4 — the run itself

Original request executed 2026-08-18 (owner's local time), HTTP 200:

```json
{"authorized":true,"receipt":{"schemaVersion":"1.0.0","receiptId":"rct_A1RqawOsLcmiTsiyWr5-FKz-6iy8QxambDmpTDWH3Uw","authorizationId":"auth_Qx7LIjfhz6eEpD_Gthno1AiRatUdxMHuUkc70_ocCDQ","providerId":"openrouter","actionId":"chat-completions","connectionId":"conn_openrouter000000","modelId":"google/gemini-3.7-flash","mode":"model-api","riskClass":"R1","inputDigest":"sha256:fe1cf1210eacd3c8c589d943ebf15319de0c42e41bc2960aff5f5bee830758f4","idempotencyKey":"q6.2-bounded-run-20260818-001","executedAt":"2026-08-18T12:01:06.136Z","outputs":{"provider":"openrouter","responseId":"gen-1787054466-P10bW2tngbv07QN8YHdC","requestedModel":"google/gemini-3.7-flash","returnedModel":"google/gemini-3.7-flash","message":{"role":"assistant","content":"INMY"},"finishReason":"length","usage":{"promptTokens":38,"completionTokens":28,"totalTokens":66,"reasoningTokens":26,"cachedTokens":0,"cost":0.0001335}}},"hubReceiptId":null}
```

**Honest note on `finishReason: "length"`:** the response content is `"INMY"`, not the full `"INMYQ6BOUNDED"` — the answer was truncated. This is NOT a governance failure; it is the 32-token bound being genuinely enforced. `gemini-3.7-flash` is a reasoning model that spent `reasoningTokens: 26` of the 32-token budget on internal reasoning before writing visible output, leaving too little room to finish the word. The bound working exactly as designed (and truncating) is itself evidence the server-side token limit is real and enforced, not merely advisory. The prompt design under-budgeted for this model's reasoning overhead; that is a design lesson for any future bounded run, not a defect in the governance path being tested.

## Q6.5 — explicit model honoured, no fallback, sensitivity/bounds respected

- `requestedModel` and `returnedModel` are both exactly `google/gemini-3.7-flash` — the explicit model was honoured, no other model was ever dispatched to.
- Source-level guarantee (`InMyConnect_Foundation__main/src/providers/openrouter.mjs`): the outbound OpenRouter request body hardcodes `provider: { allow_fallbacks: false, require_parameters: true }` and sends `model` as a single string field — there is no `models[]` fallback-chain field anywhere in this adapter.
- `idempotencyKey` in the receipt matches exactly what was sent; `inputDigest` is a `sha256:` hash, confirming the exact bounded request (not some other request) is what was recorded.
- The 32-token bound was genuinely enforced (see `finishReason: "length"` above) — bounds are respected, if perhaps too tightly for this specific model's reasoning overhead.
- Sensitivity (`PUBLIC`) is accepted by Hub policy (`allowedSensitivity: [PUBLIC, INTERNAL]`) — the request succeeded, which is the expected/allowed outcome for `PUBLIC`.

## Q6.6 — Hub authorized BEFORE the provider call

- Source-level guarantee (`InMyConnect_Foundation__main/src/connect-hub-governed-model-executor.mjs`): `executeGovernedModel()` awaits `hubRuntime.authorizeModelExecution()` then `hubRuntime.recordExecutionIntent()`, both of which throw on failure, strictly before the line that calls the provider adapter. There is no code path that reaches OpenRouter without both succeeding first.
- Runtime corroboration: Hub's aggregate status before the run was `authorizations:2, receipts:2, intents:2`; after the run (including the replay), `authorizations:3, receipts:3, intents:3` — exactly one full authorize→intent→receipt cycle happened, consistent with one real dispatch plus one no-op replay.
- Stronger black-box proof comes from the negative case, Q6.9 below: when Hub is unreachable, the request never reaches the point of even attempting a provider dispatch.

## Q6.7 — receipt recorded exactly once

Hub's own aggregate receipt count went from 2 to 3 — exactly +1, not +2, across both the original call and the identical replay call. Confirms the execution was recorded on Hub exactly once, not twice, despite two HTTP calls being made.

## Q6.8 — idempotent replay does not redispatch

Replay request (same `workflowRunId` + `idempotencyKey`, sent immediately after the original), HTTP 200:

```json
{"authorized":true,"receipt":{"schemaVersion":"1.0.0","receiptId":"rct_A1RqawOsLcmiTsiyWr5-FKz-6iy8QxambDmpTDWH3Uw", ... "executedAt":"2026-08-18T12:01:06.136Z", ... "message":{"role":"assistant","content":"INMY"}, ... "usage":{"promptTokens":38,"completionTokens":28,"totalTokens":66,"reasoningTokens":26,"cachedTokens":0,"cost":0.0001335}}},"hubReceiptId":"hubr_xdOm1Tayd8vXxRJG7lGc4i9P3m5p0J5fq7JKykiHzxE"}
```

`receiptId`, `executedAt`, `content`, and `usage` (including `cost`) are byte-for-byte identical to the original response. The only difference is `hubReceiptId`: `null` on the original response (the Hub completion write is fire-and-forget, not yet settled at response time) versus a real value on the replay (it had time to settle in between). This is expected, not evidence of a second dispatch — corroborated by Q6.7's receipt count staying at exactly +1 across both calls. **No second real OpenRouter charge occurred for the replay.**

**Known gap, disclosed rather than hidden:** this dedup is in-memory only inside the live InMyConnect process. If InMyConnect is restarted between an original call and a retry with the same idempotency key, the in-memory guard is gone and the retry would genuinely dispatch to OpenRouter a second time (Hub's own record would eventually flag the mismatch after the fact, but the double charge would already have happened). This bounded run deliberately never tested that path for real, to avoid causing exactly the double-spend it would be probing for. It remains an accepted, documented limitation of the current design, not something this acceptance record claims to have fixed.

## Q6.9 — a Hub denial blocks the provider call completely

Negative-case run (Hub process stopped, InMyConnect and InMyAI left running), distinct idempotency key `q6.9-hub-down-20260818-001`, HTTP 503:

```json
{"code":"CONNECT_HUB_UNAVAILABLE","message":"InMyHub is unavailable; no OpenRouter execution can be authorized."}
```

This is the exact fixed message from `connect-openrouter-governed-runtime.mjs`'s `hubUnavailableError()`. Source-level guarantee: `executeOpenRouterChat()` calls `selectedHubRuntime.status()` and throws this error immediately if it fails — *before* `governedExecutor.executeGovernedModel()` (the function that would call `authorizeModelExecution` and eventually the provider adapter) is ever invoked. **No OpenRouter request was attempted, no credit was spent, in this test.** This is the strongest available proof that a Hub denial blocks dispatch completely, not merely "denies after attempting."

## Q6.10 — no secret leaks in success or failure responses

- Both the success response (Q6.4/Q6.8) and the failure response (Q6.9) were manually inspected for the pattern `sk-or-v1-` (OpenRouter key prefix) and `Bearer <token>` (the bridge's own service-token header value). Neither appears anywhere in either response.
- The only credential-adjacent fields present are `authorizationId` and `hubReceiptId`/`receiptId` — all opaque IDs, not secrets.
- This manual check is exactly what Q5.5's automated permanent test already covers programmatically at the unit level (see the Q5.5 correction entry in the governance roadmap, 2026-08-18) — this run is a live, real-traffic confirmation of the same property, not a new mechanism.

## Q6.11 — token usage, cost, timeout, and crash-mid-execution replay

**Demonstrated directly, from the real receipt:** `promptTokens: 38`, `completionTokens: 28` (of which `reasoningTokens: 26`), `totalTokens: 66`, `cost: 0.0001335` (USD). Real, tiny, and fully attributable to this one bounded run.

**Explicitly out of scope for this bounded run, and why:**
- **Timeout behaviour** cannot be reliably forced against the real, healthy OpenRouter API on demand. Forcing it would require either an indefinite unreliable wait, or pointing the adapter at a deliberately-hanging stub — which is exactly what the existing automated unit tests in `InMyConnect_Foundation__main/tests/openrouter-provider.test.mjs` already do (`AbortError`/timeout-controller path). Relying on that existing coverage rather than reproducing it live was a deliberate choice, not an oversight.
- **Crash-mid-execution replay** (killing InMyConnect between intent-recording and completion, then retrying with the same idempotency key) was deliberately NOT attempted for real, because doing so risks exactly the double-real-spend scenario described as a known gap under Q6.8 above. This corner remains verified only at the design/code level (Hub's own receipt-digest mismatch detection, described in Q6.8) and at the orphan-detection level (an intent with no matching receipt after `orphanThresholdMs` triggers a Hub activity-feed warning) — neither of which was exercised live in this bounded run, to avoid the risk it would itself demonstrate.

Q6.11 is therefore marked **partially** closed: the parts that can be safely and directly demonstrated are demonstrated with real evidence above; the parts that cannot be safely forced live remain, honestly, at unit-test-level coverage only.

## Q6.12 — do not re-run to get a nicer result

The original run's truncated `"INMY"` response (see Q6.4's honest note above) was kept as the recorded evidence and was NOT re-run with a larger token budget to get a cleaner-looking result. The imperfection is disclosed rather than hidden, consistent with Q6.12's explicit instruction and this project's broader evidence-based governance culture.

## Summary

| Item | Status | Evidence |
|---|---|---|
| Q6.1 | DONE (prior) | Model pinned, `google/gemini-3.7-flash` |
| Q6.2 | DONE | This document, "Fixed parameters used" |
| Q6.3 | DONE | Owner's explicit `lanjut` confirmation before the real-spend call |
| Q6.4 | DONE | This document, "Q6.4 — the run itself" |
| Q6.5 | DONE | This document, "Q6.5" |
| Q6.6 | DONE | This document, "Q6.6" |
| Q6.7 | DONE | This document, "Q6.7" |
| Q6.8 | DONE (with a disclosed, unresolved design gap re: restart-then-retry) | This document, "Q6.8" |
| Q6.9 | DONE | This document, "Q6.9" |
| Q6.10 | DONE | This document, "Q6.10" |
| Q6.11 | PARTIAL | This document, "Q6.11" — token usage/cost demonstrated; timeout and crash-replay explicitly out of scope, unit-test coverage only |
| Q6.12 | DONE | This document, "Q6.12" |

Real cost of this entire acceptance exercise: **$0.0001335 USD** for one dispatch (the replay incurred no additional real cost); the Q6.9 negative test incurred none at all.
