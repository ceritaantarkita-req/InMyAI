# Phase 5 OpenRouter — live end-to-end acceptance record v1

Date: 2026-08-18

Status: **ACCEPTED**. This closes items 3-6 of the "Remaining Phase 5
closure" list in `docs/phase5-openrouter-chat-composer-wiring-v1.md`.

## 1. What this record is

Every prior Phase 5 checkpoint (API contract, credential boundary, provider
catalog, composer wiring) was validated by contract tests and unit tests
only. None of it had ever been exercised as a real, owner-authorized chat
request through the actual InMyAI Chat UI, dispatched to the real OpenRouter
API, and observed end to end. This record captures that first real run.

## 2. Local identity and credential setup (item 3)

Operationally configured on the owner's machine, owner-authorized in both
cases via the D3 owner passphrase gate:

- **Hub service identity** (`agent:inmyai`): provisioned via InMyHub's
  `scripts/provision-inmyai-service-credential.mjs`. This mints a 32-byte
  bearer credential (43-char base64url), of which Hub stores only a SHA-256
  digest — never the plaintext — per the Phase E contract
  (`contracts/actor-service-identity-delegation-v1.md`,
  `registry/actor-delegation-policy.json`). The plaintext value lives only
  in `INMYAI_HUB_SERVICE_TOKEN` (InMyAI's `.env`, file-based, persists
  across reboots) and in the InMyConnect bridge process's environment
  (`CONNECT_HUB_AUTHORIZATION_TOKEN`, ephemeral per process — deliberately
  not read from a `.env` file by `run-connect-server.mjs`).
- **InMyConnect OpenRouter credential**: registered via InMyConnect's
  `scripts/setup-openrouter-credential.mjs`. InMyConnect's vault stores only
  an opaque `credentialRef`; the real OpenRouter API key never crosses into
  InMyAI or Hub. `connect-registry-v1.json` records non-secret connection
  metadata only (`connectionId`, `credentialRef`, `rawValuePresent: false`).
- **Bridge-local shared secret** (`CONNECT_BRIDGE_SERVICE_TOKEN`): validated
  locally by InMyConnect for the InMyAI-to-bridge hop. Chosen to carry the
  same value as the Hub authorization token in this deployment, which the
  architecture permits but does not require.

## 3. Live end-to-end run (items 4 and 5)

Performed through the Chat composer itself (not the API test suite), with
the "OpenRouter (governed)" provider explicitly selected by the owner and a
saved connection/model from `/providers` (`google/gemini-3.7-flash`).

What was observed and what it verifies:

- **Hub authorization is real, not decorative.** Before InMyHub was running,
  every chat attempt failed closed with `503 CONNECT_HUB_UNAVAILABLE` rather
  than silently succeeding — dispatch genuinely depends on live Hub
  authorization, not just a configured token.
- **Connect dispatch validates credentials, not just presence.** A stale
  token (kept in an already-running bridge process's environment across a
  credential rotation) produced a `401 UNAUTHORIZED`, not a silent pass —
  confirming Connect actually checks the bearer value against Hub, not just
  its shape.
- **No silent fallback.** Every failure surfaced to the owner as an explicit
  bounded error in the composer (`Request failed safely: ...`) — including
  a genuine backend bug caught by this run (see below) — and never
  transparently retried against Mock or Ollama.
- **Provider output is real.** A successful run returned an actual assistant
  response from Google Gemini 3.7 Flash via OpenRouter, tagged in the UI
  with the exact expected governance reason text ("Explicit manual
  OpenRouter selection through Hub-governed InMyConnect; automatic routing
  and fallback are disabled") and a `200 OK` in server logs.
- **No OpenRouter API key leakage across the InMyAI/Hub boundary.** Confirmed
  by design (InMyAI and Hub never receive it — only InMyConnect's vault does)
  and by the existing test suite's negative assertions
  (`provider-selection.test.mjs`: no `OPENROUTER_API_KEY`, no
  `access_token`/`refresh_token` literal, no direct `openrouter.ai`
  reference, no `type="password"` field in the composer).

### Bug found and fixed during this run

The very first live chat request 400'd with `messages[0].content cannot
have surrounding whitespace`, thrown by
`connect_openrouter.py`'s `_bounded_string()` governed-input validation.
Root cause: `services/api/app/main.py` assembled the system message with a
trailing `\n\n` that was never followed by anything when a project's indexed
context was empty. Mock and Ollama never validate whitespace, so this had
never surfaced before this run was the first real exercise of the
OpenRouter path. Fixed by appending `.strip()` to the assembled
`system_message` before it enters `messages[]`. Re-tested live after the
fix; the same request completed successfully.

## 4. Operational incident and remediation (honesty note for item 5)

During this session's live troubleshooting, the Phase E service credential
value was inadvertently exposed in plaintext multiple times via chat
messages and terminal screenshots shared for debugging purposes (both an
earlier and a later credential value, across roughly five separate
exposures). This is an operational handling incident, not a defect in the
Phase 5 architecture itself — the design never requires the credential to
be typed or displayed in a shared channel, and none of the exposures
involved the OpenRouter API key itself, only the local Hub/bridge bearer
token.

Remediation: the credential was rotated via
`provision-inmyai-service-credential.mjs --rotate` on two occasions during
this window, most recently after this live E2E run succeeded, specifically
to invalidate every previously-exposed value. The rotation flow requires
the D3 owner passphrase and immediately revokes the prior credential
(`maxActiveCredentials: 1`). Post-rotation, the full flow (chat → InMyConnect
→ Hub → OpenRouter) was re-verified successfully with the new credential.

Process improvement adopted going forward: credential values are entered
directly by the machine owner into a script/terminal she runs herself and
are never requested, echoed, or repeated back through the assistant.

## 5. Tooling delivered alongside this acceptance

`start-inmy-stack.ps1` (repo-external, lives in the parent `inmy/` folder,
not part of any product repo): reads `INMYAI_HUB_SERVICE_TOKEN` from
InMyAI's `.env` once per run without ever displaying it, and starts InMyHub,
the InMyConnect bridge, and InMyAI in the correct order, skipping any that
are already running. Addresses the operational feedback that the prior
3-terminal/manual-`$env:`-sync setup was too error-prone for routine use.

## 6. Verdict

Items 3-6 of Phase 5's closure list are satisfied with live evidence, not
only contract/unit-test coverage. Phase 5 (OpenRouter governed provider) is
closed as of this record's date.
