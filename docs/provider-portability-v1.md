# V2.x Phase 5 — InMyAI portable-provider manual selection foundation

## Status

```text
PHASE5 = IN_PROGRESS
CHECKPOINT = INMYAI_PORTABLE_PROVIDER_MANUAL_SELECTION_FOUNDATION
PROVIDER_EXECUTION = NOT_AUTHORIZED
AUTOMATIC_CLOUD_ROUTING = NOT_AUTHORIZED
```

This checkpoint gives InMyAI an explicit, bounded representation of an additional cloud-provider candidate without bypassing InMyConnect or InMyHub.

It does not alter the current working Ollama/mock chat path and does not add a network provider implementation.

## Accepted upstream boundary

The first portable provider candidate is pinned to the exact accepted InMyConnect foundation:

```text
repository = ceritaantarkita-req/InMyConnect
ref        = ef39c199c302f3e6797994e0fa4a025d2a47b241
descriptor = providers/openai-official-api-v1.json
provider   = openai
```

That upstream foundation is contract-only, manual-selection-only and non-dispatching.

InMyAI must not reinterpret that contract as provider execution authority.

## Ownership

Phase 5 keeps the roadmap ownership split:

```text
InMyConnect -> credentials/auth/connection lifecycle
InMyAI      -> model catalog/manual selection/task routing
InMyHub     -> authority/export/resource/budget policy
```

Therefore this module records provider/model selection metadata only.

It does not read an API key, resolve an opaque credential handle, call a provider endpoint, authorize export, or create Hub authority.

## Manual selection contract

`services/api/app/provider_portability.py` exposes:

```text
list_portable_provider_catalog()
plan_manual_provider_selection(provider_id, model_id)
portable_provider_is_execution_authorized(provider_id)
```

The first catalog entry is deliberately bounded:

```text
provider_id                         = openai
transport                           = official-api
connection_owner                    = InMyConnect
execution_state                     = contract-only
risk_class                          = R1
selection_mode                      = manual-only
automatic_routing_allowed           = false
dispatch_allowed                    = false
credential_resolution               = INMYCONNECT_ONLY
raw_credential_exposure_allowed     = false
browser_session_credentials_allowed = false
model_discovery_state               = provider-discovery-later
default_model                       = none
```

There is intentionally no hard-coded "best" OpenAI model and no default cloud model.

A model ID must be selected explicitly by the user or a later reviewed provider-discovery surface before any provider-specific execution gate can even be considered.

## Selection result

A valid explicit selection returns metadata such as:

```text
selection_status       = SELECTED_NOT_EXECUTABLE
selection_mode         = manual
credential_resolution  = INMYCONNECT_ONLY
automatic_routing      = false
dispatch_allowed       = false
network_call_performed = false
next_gate              = HUB_CONNECT_GOVERNED_PROVIDER_EXECUTION
```

The selection object is not a credential, connection, export grant, budget grant, provider request or execution receipt.

## Fail-closed behavior

The foundation rejects:

- unknown providers;
- implicit/blank model choice;
- automatic or shadow selection mode;
- model identifiers with whitespace, query syntax or unbounded characters;
- any attempt to infer execution authority from a registered portable provider.

The source itself contains no provider HTTP client, environment-secret lookup, process execution or raw credential resolution primitive.

## Existing InMyAI runtime remains authoritative

This checkpoint intentionally does not modify:

- `ChatRequest.provider`;
- `/api/chat` provider dispatch;
- Ollama availability/onboarding;
- current automatic local routing;
- Mock fallback semantics;
- Agent task provider execution;
- browser provider selector UI.

Those remain the current product path until a later bounded checkpoint explicitly wires provider catalog/manual selection UI and, separately, provider execution authority.

An explicitly selected future cloud provider must not silently fall back to another provider. If execution is not authorized, the product must surface that state explicitly.

## GitHub Actions acceptance boundary

Current InMyAI `.github/workflows/ci.yml` uses `ubuntu-latest` and triggers on pull requests.

Hosted GitHub Actions are not accepted as candidate evidence in this program. Phase 5 acceptance uses an exact-head Ubuntu WSL local QA wrapper instead.

Because opening an InMyAI PR would automatically trigger the hosted workflow, no Phase 5 InMyAI PR should be opened until that trigger implication is separately reconciled or explicitly handled without relying on hosted Actions.

## Next checkpoint

After exact-head local acceptance, the next bounded step may expose this provider catalog/manual-selection state through InMyAI API/UI without enabling dispatch.

Later steps remain separately gated:

```text
manual provider/model selection
 -> telemetry
 -> shadow route recommendations
 -> task-family benchmark
 -> bounded auto-routing only if evidence justifies it
```

Provider dispatch itself requires a separately accepted Hub + Connect governed execution path.
