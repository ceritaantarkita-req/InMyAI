# Phase 5 OpenRouter InMyAI wiring v1

## Scope

This checkpoint makes OpenRouter the first real cloud-provider target exposed by InMyAI while preserving the InMyHub + InMyConnect authority and credential boundaries already accepted earlier in Phase 5.

Accepted upstream pins:

- InMyHub main: `dbfbb3d3fa1c6e5ff217814e8bfbb8ef5c5cc1b7`
- InMyConnect main: `65d8be8692da237961dc19a76147bab8739c8597`
- InMyConnect OpenRouter adapter: `src/providers/openrouter.mjs`
- InMyConnect governed runtime: `src/connect-openrouter-governed-runtime.mjs`
- InMyConnect Hub R1 client: `src/connect-hub-r1-http-client.mjs`

Direct OpenAI is not the Phase 5 real-provider target.

## Intended runtime path

```text
Browser / InMyAI UI
        |
        | no provider credential
        v
InMyAI local API
        |
        | Hub service identity only
        | explicit loopback HTTP
        v
InMyConnect HTTP bridge
        |
        +--> model discovery: R0/read
        |        |
        |        v
        |    OpenRouter /models/user
        |
        +--> chat: R1/model-api
                 |
                 v
            InMyHub authorize
                 |
                 v
            InMyConnect vault
                 |
                 v
            OpenRouter adapter
                 |
                 v
            InMyHub record receipt
```

The final InMyConnect HTTP bridge shown above is the remaining local transport boundary after this InMyAI wiring checkpoint. The accepted Connect repository already contains the assembled governed runtime, but it does not yet expose these OpenRouter runtime operations as a loopback HTTP service. Therefore normal QA for this checkpoint mocks that local boundary and does not claim a live end-to-end provider call.

## Provider catalog

The portable-provider catalog now exposes one Phase 5 real-provider target:

- provider: `openrouter`
- execution state: `hub-governed`
- risk: `R1`
- model selection: manual only
- automatic routing: disabled
- silent fallback: disabled
- default cloud model: none
- model discovery: account-filtered through InMyConnect
- allowed sensitivity: `PUBLIC`, `INTERNAL`
- blocked sensitivity: `SENSITIVE`, `RESTRICTED`
- max input: `262144` bytes
- max requested output: `8192` tokens

A model whose slug begins with another provider name is still reached through OpenRouter; InMyAI does not change network provider based on the slug.

## Credential boundary

There are two different credentials and they must not be confused.

### Hub service identity

`INMYAI_HUB_SERVICE_TOKEN` is the local service credential used by InMyAI to identify itself as the credentialed `agent:inmyai` service to the governed Hub/Connect path.

It is:

- server-side only;
- stored as a Pydantic `SecretStr`;
- never returned by status or provider APIs;
- never placed in `NEXT_PUBLIC_*` configuration;
- never written to browser storage.

### OpenRouter API key

The OpenRouter API key does **not** belong in InMyAI.

It remains inside the InMyConnect credential boundary and may be unwrapped only transiently by the OpenRouter provider adapter at dispatch time. The browser, InMyAI API, and InMyHub never receive the raw OpenRouter key.

## Local Connect client

`services/api/app/connect_openrouter.py` is deliberately not an OpenRouter client. It talks only to the future local InMyConnect bridge.

Boundary rules:

- plain HTTP only;
- explicit IP literal required;
- `127.0.0.1` or `::1` only;
- explicit port required;
- URL credentials, paths, query strings, and fragments rejected;
- redirects disabled;
- timeout bounded to 1-60 seconds;
- response bounded to 2 MiB;
- response/network errors sanitized;
- Hub service token forwarded only as the local Bearer identity;
- no provider API origin in this module.

Expected bridge routes:

- `GET /api/openrouter/status`
- `POST /api/openrouter/models`
- `POST /api/openrouter/chat`

## Model discovery

The UI requires an opaque `conn_...` InMyConnect connection ID. It then calls the InMyAI model-discovery endpoint, which forwards only:

- `connectionId`
- an idempotency key

The intended Connect runtime uses its R0/read `models-list` adapter and the authenticated OpenRouter `/api/v1/models/user` endpoint. No Hub R1 execution authorization is needed for model discovery.

The UI does not invent or default a cloud model. The user explicitly chooses from the discovered account model list.

Browser persistence is limited to:

- opaque connection ID;
- explicit selected model ID.

No API key, access token, refresh token, Hub service token, or credential envelope is stored in browser state.

## Governed chat

`ChatRequest` now permits `provider='openrouter'` and requires, for actual OpenRouter dispatch:

- `connection_id`
- explicit `model`
- `idempotency_key`
- `input_sensitivity` (`PUBLIC` or `INTERNAL`)
- bounded requested output tokens

For an explicit OpenRouter request, InMyAI may reuse the deterministic local router only to classify the task and context budget. It then pins the decision provider back to `openrouter`; the router may not substitute another cloud provider or a local model.

The runtime call carries:

- deterministic workflow correlation;
- deterministic delegation correlation used for audit binding;
- opaque connection ID;
- explicit model ID;
- idempotency key;
- sensitivity and output budget;
- normalized system/user messages.

If the governed OpenRouter call fails, InMyAI returns a bounded failure. It does **not** silently fall back to Mock or Ollama.

## Updated execution planner

`provider_execution_contract.py` is still a metadata-only planner. It now reflects the accepted upstream state:

- Hub R1 provider execution enabled;
- Hub decision `execute`;
- credentialed service identity `agent:inmyai`;
- Phase E mutation delegation remains `mutate` only;
- Connect R1/model-api executor accepted;
- OpenRouter governed runtime accepted.

A valid intent with an opaque connection ID is therefore `GOVERNED_EXECUTION_READY` for the local Connect HTTP runtime. The planner itself still performs no credential resolution, Hub call, provider dispatch, or network request.

## UI checkpoint

The `/providers` page now provides the safe configuration surface:

1. choose OpenRouter;
2. enter only the opaque InMyConnect connection ID;
3. load account-filtered models;
4. explicitly choose one model;
5. save only connection/model metadata locally.

The existing main Chat composer is intentionally not modified in this checkpoint because the final Connect HTTP bridge does not exist yet. Adding an OpenRouter option to the normal composer before that bridge exists would present a visibly executable control whose required local runtime is unavailable. The API contract is wired and tested now; normal-chat UI handoff is part of the bridge/live-E2E closure checkpoint.

## Acceptance boundary

Normal QA must prove:

- exact branch head equals the remote candidate;
- full existing InMyAI QA remains green;
- provider catalog is OpenRouter/manual/no-default;
- model discovery is through the local Connect API contract;
- no raw OpenRouter credential field exists in ChatRequest or browser UI;
- no direct `openrouter.ai` or `api.openai.com` endpoint exists in InMyAI runtime code;
- explicit OpenRouter failure does not invoke Mock fallback;
- Hub service token is never exposed in API responses;
- hosted CI remains manual-only;
- QA worktree is clean after deterministic generated-file cleanup.

Normal QA spends no OpenRouter credit.

## Remaining Phase 5 closure

After this checkpoint is accepted and merged:

1. expose the accepted InMyConnect governed OpenRouter runtime through a bounded loopback HTTP bridge;
2. connect the standard InMyAI Chat composer to the saved explicit OpenRouter connection/model selection;
3. configure the local Hub service identity and InMyConnect OpenRouter credential envelope;
4. run one explicit owner-authorized live OpenRouter end-to-end acceptance;
5. verify Hub authorization, Connect dispatch, provider output, receipt recording, no fallback, and no secret leakage;
6. close Phase 5 only after that live evidence is green.
