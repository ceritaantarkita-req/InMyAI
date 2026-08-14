# Phase 5 — Governed provider execution contract

## Status

```text
BASE_MAIN = 51280527dda74fa2292d16a2824b355fc6220367
PORTABLE_SELECTION = MERGED
GOVERNED_EXECUTION_CONTRACT = IMPLEMENTED_FOR_ACCEPTANCE
REAL_PROVIDER_EXECUTION = NOT_AUTHORIZED
AUTOMATIC_CLOUD_ROUTING = NOT_AUTHORIZED
SILENT_FALLBACK = NOT_AUTHORIZED
```

This checkpoint defines and implements the fail-closed planning contract that must exist before InMyAI can request a real portable-provider execution.

It does **not** send a request to OpenAI or any other cloud provider.

## Why this gate is necessary

The current upstream boundaries do not yet authorize the OpenAI R1 execution path.

The accepted OpenAI provider descriptor is pinned to:

```text
repository: ceritaantarkita-req/InMyConnect
ref:        ef39c199c302f3e6797994e0fa4a025d2a47b241
path:       providers/openai-official-api-v1.json
riskClass:  R1
state:      contract-only
```

That descriptor allows only `PUBLIC` and `INTERNAL` sensitivity, blocks `SENSITIVE` and `RESTRICTED`, caps input at 262,144 bytes, and caps requested output at 8,192 tokens.

The current InMyHub main accepted by this checkpoint is pinned to:

```text
repository: ceritaantarkita-req/inmyhub
ref:        cb660413941075337bd14aafedc79f998e01727a
policy:     data/policy/authority-policy.json
```

Its authority policy is still:

```text
mode = plan-only
executionEnabled = false
R1 = plan-only
agent:inmyai delegation allowedSubjectModes = mutate
```

The current InMyConnect main accepted by this checkpoint is pinned to:

```text
repository: ceritaantarkita-req/InMyConnect
ref:        08b381203e8a3b7c379a1b7da3683a286b91d9f7
model:      src/connect-model.mjs
governed:   src/connect-hub-governed-executor.mjs
vault:      docs/connect-vault-boundary-v1.md
```

That Connect foundation currently exposes:

```text
action modes = read
risk classes = R0
credential handles = crf_...
connection ids = conn_...
Hub-governed execution = read/R0 only
```

Therefore an OpenAI `model-api` request classified as R1 must remain blocked until Hub and Connect add matching execution authority and executor support.

## Implemented module

```text
services/api/app/provider_execution_contract.py
```

Primary interface:

```python
plan_governed_provider_execution(payload)
```

This function is deterministic planning code. It performs no Hub call, no Connect call, no credential resolution, no provider network call, and no fallback.

## Accepted planning input

Only these fields are accepted:

```json
{
  "provider_id": "openai",
  "model_id": "user-chosen-model",
  "data_sensitivity": "INTERNAL",
  "input_bytes": 4096,
  "requested_output_tokens": 1024,
  "idempotency_key": "phase5-contract-0001",
  "input_digest": "sha256:<64-lowercase-hex>",
  "connection_id": "conn_<opaque-id>"
}
```

`connection_id` is optional at this planning gate. If absent, the returned plan includes a connection-binding blocker.

Raw prompt/content is intentionally **not accepted** by this contract. The caller supplies an input digest and byte count instead. This prevents a planning operation from becoming a hidden data-export path.

Credential-like fields are rejected. InMyAI must not accept or store raw API keys, tokens, passwords, passphrases, private keys, or credential values.

## Execution plan result

For the current accepted upstream state, a structurally valid OpenAI execution intent returns:

```text
execution_status = EXECUTION_NOT_AUTHORIZED
readiness = BLOCKED_UPSTREAM_CAPABILITY_GAP
network_call_performed = false
provider_dispatch_performed = false
credential_resolution_performed = false
hub_authorization_performed = false
automatic_routing_allowed = false
silent_fallback_allowed = false
fallback_performed = false
```

It also returns a deterministic `intent_digest` bound to the non-secret execution metadata, provider descriptor ref, Hub ref, Connect ref, input digest, and idempotency key.

## Current mandatory blockers

For an otherwise valid PUBLIC/INTERNAL OpenAI plan, the current upstream state produces these blockers:

```text
PROVIDER_DESCRIPTOR_CONTRACT_ONLY
HUB_EXECUTION_DISABLED
HUB_R1_PLAN_ONLY
HUB_AGENT_EXECUTE_DELEGATION_UNAVAILABLE
CONNECT_R1_MODEL_EXECUTOR_UNAVAILABLE
```

If no opaque connection is supplied:

```text
CONNECT_CONNECTION_NOT_BOUND
```

Policy-specific blockers are added when applicable:

```text
EXPORT_SENSITIVITY_BLOCKED
PROVIDER_INPUT_LIMIT_EXCEEDED
PROVIDER_OUTPUT_LIMIT_EXCEEDED
```

These blockers are evidence, not suggestions to bypass governance.

## Credential boundary

The current Connect vault contract uses opaque `crf_...` credential handles and excludes raw credential values from normal metadata flow.

InMyAI does not receive a raw credential or resolve the credential handle in this checkpoint. The execution planner accepts at most an opaque `connection_id` and records it as:

```text
OPAQUE_ID_ACCEPTED_NOT_RESOLVED
```

Credential resolution remains owned by InMyConnect.

## No-silent-fallback rule

Portable-provider execution must never silently fall back to Mock or Ollama after the user explicitly selected a cloud provider.

Current contract:

```text
silent_fallback_allowed = false
fallback_performed = false
```

A denied, unavailable, timed-out, policy-blocked, or failed future cloud execution must surface that state explicitly.

The existing `/api/chat` execution path remains unchanged in this checkpoint:

```text
auto
mock
ollama
```

## Audit and idempotency boundary

The contract requires:

```text
idempotency_key
input_digest = sha256:<digest>
```

The planner emits a deterministic `intent_digest` so later Hub authorization, Connect execution, and execution receipts can be tied to the same bounded intent.

This checkpoint does not claim that the current Hub/Connect runtime has consumed that intent. Both fields are preparation for the next execution-bearing gate.

## Explicit non-goals

This checkpoint does not:

- call `/api/chat` through OpenAI;
- call OpenAI `/responses`;
- perform provider model discovery;
- resolve a Connect credential;
- expose a credential handle value to a model;
- enable R1 execution in InMyHub;
- add an R1/model-api adapter to InMyConnect;
- mutate InMyHub or InMyConnect;
- enable automatic cloud routing;
- permit silent fallback;
- claim real provider quality or billing acceptance.

## Required regression evidence

Acceptance must prove:

- the exact current Hub and Connect refs are pinned;
- Hub remains `executionEnabled=false` and R1 plan-only in the contract snapshot;
- Connect remains read/R0-only in the contract snapshot;
- the accepted OpenAI R1 descriptor limits are pinned;
- valid R1 execution intent remains `EXECUTION_NOT_AUTHORIZED`;
- opaque `connection_id` is accepted only as metadata and is never resolved;
- blocked sensitivity and provider size/token limits fail closed;
- raw prompt/content fields and credential-like fields are rejected;
- intent digest is deterministic and input-digest-bound;
- no network/provider-dispatch primitive exists in the execution-contract module;
- current Chat execution providers remain `auto | mock | ollama`;
- hosted Actions remain manual-only;
- full local InMyAI QA and production build pass;
- deterministic QA cleanup leaves the worktree clean.

## Next execution-bearing gate

Real OpenAI execution remains blocked until **both** upstream capabilities exist and are separately accepted:

```text
1. InMyHub R1 execution authority
   - execution no longer globally disabled for the accepted capability;
   - exact R1 provider/model capability is manifest-bound;
   - agent:inmyai execute delegation/authority is defined;
   - idempotency/audit/receipt requirements are explicit;
   - export policy is evaluated before dispatch.

2. InMyConnect R1 model-api executor
   - R1/model-api action is explicitly registered;
   - opaque connection -> credential resolution stays inside Connect;
   - provider adapter is official-API only;
   - request limits and sensitivity constraints are enforced;
   - execution receipt is recorded back to Hub;
   - timeout/provider errors are explicit;
   - no silent fallback exists.
```

Until those gates are accepted, InMyAI must remain unable to dispatch the selected portable provider.
