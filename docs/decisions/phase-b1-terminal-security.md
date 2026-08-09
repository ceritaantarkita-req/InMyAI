# Decision record: Phase B1 terminal browser-boundary security

Date: 2026-08-09
Status: implemented, CI-verified, merged to `main`
Runtime merge commit: `17cc6e772c38b3aac8b67818283cc55b203df31c`

## Problem

InMyAI's Terminal is intentionally a real, unsandboxed local shell. That product decision remains valid, but it makes the WebSocket handshake a privilege boundary: once a client can send terminal keystrokes, it can exercise the current OS user's authority.

The original implementation accepted `/ws/terminal` before validating the browser's `Origin`. Ordinary HTTP CORS middleware does not protect WebSocket handshakes. A malicious browser page could therefore attempt a Cross-Site WebSocket Hijacking (CSWSH) connection to the local InMyAI API and, if accepted, type into the real shell.

Binding the API to localhost is not sufficient protection against this browser-origin threat because a remote web page can initiate network requests toward loopback services from the user's browser.

## Decision

Keep the Terminal as a real PTY, but fail closed at the WebSocket boundary before `accept()` and before a PTY process is created.

The terminal WebSocket accepts only exact known InMyAI origins:

- `http://127.0.0.1:3000`
- `http://localhost:3000`
- `http://tauri.localhost`
- `https://tauri.localhost`
- `tauri://localhost`

Missing or any other Origin is rejected with WebSocket policy-violation code `1008`.

## Why the Terminal policy is stricter than ordinary HTTP CORS

InMyAI has legitimate development scenarios where ordinary HTTP features may be accessed from a private-LAN browser origin. That broader LAN behavior is not inherited by the real-shell WebSocket.

During Phase B1 review, the first patch allowed RFC1918 `:3000` origins to mirror the HTTP CORS policy. The adversarial review rejected that design: content served from an untrusted LAN origin could otherwise gain the same real-shell authority. The final implementation deliberately rejects private-LAN browser origins for `/ws/terminal`.

This separation is intentional:

- ordinary local/LAN HTTP features can retain their existing development behavior;
- the PTY privilege boundary is restricted to loopback InMyAI UI and the trusted Tauri application origin.

## Ordering invariant

`run_terminal_session()` performs the Origin authorization first. Only a trusted request may proceed to:

1. `websocket.accept()`;
2. `PtySession(...)` construction;
3. shell I/O relay.

An untrusted request therefore cannot cause a shell process to be spawned as a side effect of a rejected handshake.

## Regression tests

`services/api/tests/test_terminal_security.py` adds platform-independent coverage for the browser boundary without needing to spawn a real PTY:

- loopback and Tauri origins are accepted;
- missing Origin is rejected;
- public malicious origins are rejected;
- localhost/lookalike origins are rejected;
- private-LAN origins are rejected;
- rejected requests close with code `1008`;
- a rejected request is proven to exit before `PtySession` construction.

The existing `test_terminal.py` remains responsible for direct PTY behavior.

## CI evidence

PR #2 (`security: close terminal cross-site WebSocket hijacking`) completed successfully on GitHub Actions on 2026-08-09.

The successful CI job executed:

- web TypeScript typecheck: PASS;
- frontend tests: **20/20 PASS**;
- backend tests: **141 passed, 1 skipped**;
- Next.js production build: PASS.

This is the current automated baseline after Phase B1 and supersedes the older 2026-07 QA counts.

## Assurance level

The original CSWSH finding is **CLOSED for the intended browser/Tauri local-first boundary at automated evidence level E3**:

- source path inspected;
- regression tests exercise the authorization boundary;
- CI executed the complete backend suite and production web build successfully.

A fresh post-change live Windows check of the Tauri-origin WebSocket handshake was not performed during this Phase B1 patch. The product previously had a working real Windows Tauri shell, but a new Windows runtime check should be completed before representing the Phase B1 Origin change itself as fresh E4 Windows evidence.

## Residual risk and non-goals

- The Terminal remains intentionally unsandboxed after a trusted client connects.
- This control is not intended to defend against a malicious process already executing as the same OS user; such a process already has equivalent or greater local authority.
- This change does not add multi-user authentication or remote-terminal access.
- Do not broaden the terminal Origin list to generic suffixes, wildcards, or private-LAN regexes without a new security review.

## Verification commands

```bash
python -m pytest services/api/tests/test_terminal_security.py -q
python -m pytest services/api/tests/test_terminal.py -q
npm run typecheck:web
npm run test:web
npm run build:web
```
