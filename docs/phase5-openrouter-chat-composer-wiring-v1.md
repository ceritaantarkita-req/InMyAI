# Phase 5 OpenRouter chat composer wiring v1

## Scope

This checkpoint closes item 2 of the "Remaining Phase 5 closure" list in
`docs/phase5-openrouter-inmyai-wiring-v1.md`: it connects the standard InMyAI
Chat composer to the explicit OpenRouter connection/model selection a user
already saved on `/providers`.

`docs/phase5-openrouter-inmyai-wiring-v1.md` deliberately left the Chat
composer untouched because, at that checkpoint, the local InMyConnect HTTP
bridge (`services/api/app/connect_openrouter.py`'s counterpart on the
InMyConnect side) did not yet exist. Adding a visible OpenRouter control to
the composer before that bridge existed would have presented an executable
option with no working local runtime behind it.

That bridge now exists (InMyConnect's `src/connect-openrouter-http-bridge.mjs`,
mounted by `src/connect-server.mjs` and exposed by `scripts/run-connect-server.mjs`)
and exposes exactly the three routes InMyAI's client already expected:

- `GET /api/openrouter/status`
- `POST /api/openrouter/models`
- `POST /api/openrouter/chat`

With the runtime boundary this checkpoint depended on now real and reachable
at `http://127.0.0.1:8766` (InMyAI's `INMYAI_CONNECT_BASE_URL` default), the
composer wiring this doc describes is safe to add.

## What changed

`apps/web/src/components/Workspace.tsx` (`ChatView`):

- The chat provider dropdown gains a fourth option, `OpenRouter (governed)`,
  alongside the existing `Automatic router` / `Safe mock` / `Ollama local`.
- On mount, the composer reads (never writes) the two `localStorage` keys
  `/providers` already owns: `inmyai:openrouter:connectionId` and
  `inmyai:openrouter:modelId`.
- The OpenRouter option is `disabled` whenever either value is missing or
  empty. There is no default connection or model — exactly the same
  explicit-only rule `/providers` already enforces on the API contract side.
- When `provider === 'openrouter'`, `send()` includes `connection_id`,
  `model`, and a freshly minted `idempotency_key` in the `/api/chat` request
  body (`services/api/app/schemas.py`'s `ChatRequest` already accepted these
  fields since the prior checkpoint; the composer simply populates them now).
  A guard on `send()` itself (not just the disabled `<option>`) refuses to
  fire an OpenRouter request if the saved connection/model went missing
  between render and submit.
- A small inline hint next to the dropdown either shows the currently
  configured model (`Model: <id> · Change`) or, if nothing is configured yet,
  links out to `/providers` to configure it.

`apps/web/tests/provider-selection.test.mjs`:

- Replaces the prior guard test (which asserted the OpenRouter option must
  *not* exist yet) with two tests asserting the new option exists, is
  disabled without a saved connection/model, and that the composer only ever
  reads the existing `/providers`-owned `localStorage` keys — it does not
  duplicate, invent, or default a connection/model of its own.
- Keeps the same credential-safety assertions already used for `/providers`
  (no `type="password"`, no `OPENROUTER_API_KEY`, no `access_token` /
  `refresh_token` literal, no direct `openrouter.ai` reference) applied to
  `Workspace.tsx` as well.

## What did not change

- `AgentsView`'s background-task provider selector (`apps/web/src/components/Workspace.tsx`,
  the `/api/tasks` flow) is untouched — it is a separate feature from the
  Chat composer and was not part of this checkpoint's scope.
- `/providers` itself, `services/api/app/*`, and `.env.example` are untouched.
  The API contract, credential boundary, and provider catalog were already
  accepted in `docs/phase5-openrouter-inmyai-wiring-v1.md`.
- No fallback was added. A failed governed OpenRouter call still returns a
  bounded failure in the composer (existing `catch` block renders
  `Request failed safely: ...`); it does not silently retry against Mock or
  Ollama.

## Remaining Phase 5 closure

Per `docs/phase5-openrouter-inmyai-wiring-v1.md`'s original list:

1. ~~expose the accepted InMyConnect governed OpenRouter runtime through a
   bounded loopback HTTP bridge~~ — done (InMyConnect
   `connect-openrouter-http-bridge.mjs`).
2. ~~connect the standard InMyAI Chat composer to the saved explicit
   OpenRouter connection/model selection~~ — done by this checkpoint.
3. ~~configure the local Hub service identity and InMyConnect OpenRouter
   credential envelope~~ — done and now captured as an in-repo acceptance
   record: see `docs/phase5-openrouter-live-e2e-acceptance-v1.md`.
4. ~~run one explicit owner-authorized live OpenRouter end-to-end acceptance
   through the Chat composer itself (not just the API contract tests) and
   record the result~~ — done 2026-08-18, recorded in
   `docs/phase5-openrouter-live-e2e-acceptance-v1.md`. This same run also
   surfaced and led to a fix for a real bug (`services/api/app/main.py`'s
   system message failing OpenRouter's whitespace validation on empty
   project context).
5. ~~verify Hub authorization, Connect dispatch, provider output, receipt
   recording, no fallback, and no secret leakage for that live run~~ — done,
   see the same acceptance record for what was verified and how, including
   an honest account of an operational credential-exposure incident during
   this window and its remediation.
6. ~~close Phase 5 only after that live evidence is green~~ — **done. Phase 5
   is closed as of 2026-08-18.**

**Status: Phase 5 (OpenRouter governed provider) is CLOSED.** All six items
above have live evidence, not just contract/unit-test coverage. Any further
OpenRouter work (additional models, spend-cap policy, multi-connection
support, etc.) is new scope, not a Phase 5 reopening.
