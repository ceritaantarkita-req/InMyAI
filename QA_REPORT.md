# InMyAI QA Report

Date: 2026-08-09
Scope: Phase B1 terminal browser-boundary security refresh, with current CI baseline and explicit historical evidence boundaries.

## Current automated result

The Phase B1 pull request was executed by GitHub Actions against the security change before merge.

| Check | Result |
|---|---|
| Strict TypeScript (`npm run typecheck:web`) | PASS |
| Frontend tests (`npm run test:web`) | **20/20 PASS** |
| FastAPI tests (`python -m pytest services/api/tests -q`) | **141 passed, 1 skipped** |
| Next.js production build (`npm run build:web`) | PASS |
| Phase B1 Terminal Origin regression coverage | PASS — included in backend suite |
| Visual/screenshot regression | NOT RE-RUN in Phase B1 |
| Live post-change Windows Tauri WebSocket Origin handshake | NOT RE-RUN in Phase B1 |

The successful Phase B1 runtime was merged to `main` as:

`17cc6e772c38b3aac8b67818283cc55b203df31c`

These counts supersede the older 2026-07 report values of 15 frontend tests and 134 backend tests.

## Phase B1 security closure

### Finding

The Terminal is a genuine PTY-backed local shell. The previous `/ws/terminal` flow accepted a WebSocket without first validating the browser's `Origin`. Because WebSockets are not protected by ordinary HTTP CORS middleware, a malicious web page could attempt Cross-Site WebSocket Hijacking against the local shell endpoint.

### Implemented control

`services/api/app/terminal.py` now validates the WebSocket Origin before `websocket.accept()` and before `PtySession` is constructed.

Accepted exact origins:

- `http://127.0.0.1:3000`
- `http://localhost:3000`
- `http://tauri.localhost`
- `https://tauri.localhost`
- `tauri://localhost`

Missing or untrusted origins fail closed with WebSocket policy-violation code `1008`.

Private-LAN browser origins are intentionally rejected for the Terminal even though ordinary InMyAI HTTP development may support a broader LAN CORS policy. The real-shell boundary is deliberately stricter.

### Regression tests

`services/api/tests/test_terminal_security.py` verifies that:

- trusted loopback/Tauri origins are allowed;
- missing Origin is rejected;
- public malicious origins are rejected;
- localhost/lookalike values are rejected;
- private-LAN origins are rejected;
- rejected handshakes close with code `1008`;
- an untrusted connection returns before a PTY process can be spawned.

The pre-existing `test_terminal.py` continues to cover direct PTY behavior.

Full rationale: `docs/decisions/phase-b1-terminal-security.md`.

## Assurance boundary

The browser-origin CSWSH finding is **CLOSED at E3** for the intended local browser/Tauri boundary:

- the exact source path was inspected;
- focused security regression tests were added;
- the complete backend suite passed in CI;
- frontend tests/typecheck passed;
- the production Next.js build passed.

Phase B1 did **not** perform a fresh live Windows test proving the updated Tauri Origin handshake through a real PTY session. InMyAI previously had a successful Windows Tauri desktop-shell run, but that historical evidence predates this Origin check. A fresh Windows runtime check is required before upgrading the Phase B1-specific evidence to E4 on Windows.

The Terminal also remains intentionally unsandboxed after a trusted connection is established. Phase B1 closes the browser-origin entry weakness; it does not convert the real shell into a restricted command environment.

## Current automated coverage context

The backend suite now includes the prior core coverage plus the Phase B1 security regression. Existing areas include:

- project registration and allowed-root enforcement;
- isolated test runtime/state;
- file indexing and search;
- DOCX/XLSX/PPTX parsing;
- AST/code-relation extraction;
- Git read-only inspection;
- model routing and Ollama onboarding;
- OCR/local-tool dispatch;
- multi-agent task runtime;
- stale-write detection and atomic writes;
- Explorer browse policy;
- direct PTY behavior;
- **Terminal WebSocket Origin authorization**;
- allowed-root UI APIs;
- background indexing and folder-scope guardrails;
- Graphify import.

Frontend CI currently reports 20 passing tests covering the shipped web helpers/navigation behavior included in the repository test command.

## Historical smoke, simulation, desktop, and visual evidence

The Phase B1 PR intentionally changed only the Terminal WebSocket authorization boundary and its tests. It did not regenerate every earlier product artifact.

### Existing smoke / engine evidence

The repository already contains prior smoke and engine-simulation evidence from the earlier InMyAI build phases, including `SMOKE_REPORT.json` and `docs/qa/ENGINE_SIMULATION_3X.json`. Those remain historical evidence for the broader application and were **not newly rerun as part of the Phase B1 GitHub Actions job**.

Do not interpret Phase B1's green CI as a new three-round whole-product simulation result. The current Phase B requirement for simulation 3× was executed on InMyHub, whose security runtime was materially changed in B2.

### Tauri desktop shell

A previous real Windows run confirmed that the Tauri shell compiled and opened successfully after fixes for `allowedDevOrigins` and Tauri capability permissions. See `docs/decisions/tauri-desktop-shell.md`.

That proves historical desktop-shell viability, not the newly introduced Phase B1 Origin policy. Re-run the Terminal once on the target Windows laptop before claiming fresh Windows E4 for this security patch.

### Visual verification

The last recorded screenshots remain the historical 2026-07 visual evidence in `docs/qa/`. They predate several later workspace changes and were not regenerated in Phase B1. Phase B1 has no intended UI layout change, but this report does not silently promote old screenshots into current visual verification.

## Recommended release checks after Phase B1

Before a user-facing Windows release:

1. Start the normal InMyAI desktop/Tauri development or release path.
2. Open Terminal and confirm a real PowerShell session connects successfully.
3. Run a harmless command and resize the terminal.
4. Confirm ordinary loopback browser mode still connects.
5. Confirm a browser page from a non-approved/LAN origin cannot establish the Terminal WebSocket.
6. Re-run the repository's full CI/local QA commands after any further source change.

## Conclusion

Phase B1 successfully closes the previously open browser-origin Terminal finding without weakening the product decision that Terminal is a real local shell. The code is merged, the security regression is in the permanent suite, and GitHub CI passed the current backend/frontend/build gates.

The remaining verification gap is narrow and explicit: a fresh post-change real Windows/Tauri terminal connection should be run before Phase B1 is represented as E4 on Windows. No broader remote/multi-user terminal capability was introduced.
