# V2.x Phase 5 — Provider selection API/UI checkpoint

## Status

```text
BASE_MAIN = 063a094b08bcbedaac0f59bb3c20952d0cd12be4
FOUNDATION = MERGED
CHECKPOINT = PROVIDER_SELECTION_API_UI
PROVIDER_EXECUTION = NOT_AUTHORIZED
AUTOMATIC_CLOUD_ROUTING = NOT_AUTHORIZED
```

This checkpoint exposes the already-merged portable-provider catalog and manual-selection plan through the InMyAI product surface without turning a portable provider into an executable chat provider.

## Critical architecture boundary

The current Chat composer provider selector is an execution selector. It feeds `ChatRequest.provider`, whose accepted execution values are currently:

```text
auto
mock
ollama
```

`POST /api/chat` routes those values into the existing local router and may execute Mock, Ollama, or a deterministic local tool.

Therefore a portable cloud provider such as `openai` must **not** simply be added to that selector or to `ChatRequest.provider` in this checkpoint. Doing so would collapse selection metadata and execution authority into one surface.

Portable provider selection must remain a separate, visibly non-executable product surface.

## Backend API contract

Expose the already-accepted functions from `services/api/app/provider_portability.py` through bounded read/plan endpoints:

```text
GET  /api/providers/portable
POST /api/providers/portable/select
```

### GET `/api/providers/portable`

Returns catalog metadata only.

It must not:

- resolve credentials;
- read environment secrets;
- call provider endpoints;
- perform model discovery over the network;
- authorize dispatch;
- mutate chat/runtime provider state.

### POST `/api/providers/portable/select`

Request:

```json
{
  "provider_id": "openai",
  "model_id": "user-entered-model-id",
  "selection_mode": "manual"
}
```

Response is the existing non-executable selection plan and must preserve:

```text
selection_status = SELECTED_NOT_EXECUTABLE
credential_resolution = INMYCONNECT_ONLY
automatic_routing_allowed = false
dispatch_allowed = false
network_call_performed = false
next_gate = HUB_CONNECT_GOVERNED_PROVIDER_EXECUTION
```

Invalid provider IDs, blank/unbounded model IDs, and non-manual selection must fail closed with a bounded client error.

## UI contract

Add a dedicated portable-provider selection surface that is separate from the existing execution-provider dropdown.

The surface must clearly communicate:

```text
Selection only
Not connected for execution
Credentials stay owned by InMyConnect
No automatic routing
```

The user may:

1. view registered portable providers;
2. choose one explicitly;
3. enter a model ID explicitly;
4. create a manual selection plan;
5. see the resulting `SELECTED_NOT_EXECUTABLE` state.

The user may **not** send chat through that provider in this checkpoint.

The existing chat execution selector must remain unchanged:

```text
Automatic router
Safe mock
Ollama local
```

## State handling

Portable selection state is presentation/planning metadata only. Do not persist provider credentials or raw tokens.

If client-side persistence is added for convenience, only bounded non-secret values may be persisted, for example:

```text
provider_id
model_id
selection_status
```

No API key, cookie, browser session credential, OAuth token, credential handle content, or secret-derived material may be stored by this UI.

## Explicit non-goals

This checkpoint does not:

- expand `ChatRequest.provider` beyond `auto | mock | ollama`;
- change `/api/chat` dispatch;
- call OpenAI or another portable provider;
- read InMyConnect credentials;
- implement provider authentication;
- perform provider model discovery;
- automatically route cloud requests;
- silently fall back from a selected cloud provider to Mock/Ollama;
- modify Agent task provider execution.

## Regression requirements

Backend tests must prove:

- catalog endpoint exposes the accepted OpenAI descriptor;
- selection endpoint returns `SELECTED_NOT_EXECUTABLE`;
- invalid provider/model/mode requests fail closed;
- no portable-provider selection call performs network or secret resolution;
- existing `/api/chat` provider schema remains `auto | mock | ollama`.

Web tests/static checks must prove:

- the existing execution provider options remain present and unchanged;
- the portable-provider UI is explicitly marked selection-only/non-executable;
- portable-provider model input is explicit, not defaulted to a cloud model;
- the portable-provider UI never sends `provider: openai` to `/api/chat`;
- no raw credential input is introduced.

## Acceptance sequence

```text
new branch from accepted main
  -> bounded API surface
  -> dedicated selection-only UI surface
  -> focused backend regression
  -> focused web/static regression
  -> full InMyAI local QA
  -> production Next.js build
  -> deterministic QA worktree cleanup
  -> exact-head acceptance
  -> final diff audit
  -> PR
```

Hosted GitHub Actions remain manual-only and are not acceptance evidence.

## Next gate after this checkpoint

A successful API/UI checkpoint still does not authorize provider execution.

The next execution-bearing checkpoint must separately define and accept the Hub + InMyConnect governed execution path, including credential-handle resolution, export/resource/budget authority, provider request policy, failure semantics, audit evidence, and explicit no-silent-fallback behavior.
