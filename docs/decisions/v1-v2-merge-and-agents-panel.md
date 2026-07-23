# Decision record: v1/v2 merge, Agents Workspace panel, config fix

Date: 2026-07-23
Status: done, verified, committed on `main`

This document exists so you (Amanda) can verify what changed and why without
re-deriving it from the diff. Each section says: what the problem was, what
was chosen, why, what else was considered, and exactly how to check it
yourself.

## 1. Which project survived: v1

`InMyAI_FullStack` (v1) is now the one and only InMyAI project.
`InMyAI_FullStack-v2` has been deleted from the demo folder — every real
capability it had that v1 lacked was ported over first (see section 2), so
nothing was lost by removing it.

**Why v1 and not v2:** v1 had the stronger foundations — better AST-based
code-relation extraction (tree-sitter, not regex), a cleaner service layer,
and it was already ahead on the Ollama onboarding wizard. v2's real
advantages were narrower and portable: the agent runtime, stale-write
detection, PPTX parsing, and the local-ui fallback. Porting four self-
contained things into the stronger codebase was less risky than porting v1's
more deeply-integrated advantages into v2.

**How to verify:** `ls` the demo folder — only `InMyAI_FullStack` remains.

## 2. What was ported from v2 into v1 (recap from the merge session)

| Feature | Where | Why chosen over alternatives |
|---|---|---|
| Multi-agent task orchestration | `agent_runtime.py` (new file) | Copied verbatim — v2's implementation already matched v1's coding conventions and needed no changes, only new `agents`/`agent_events` tables (added via `CREATE TABLE IF NOT EXISTS`) and new columns on the existing, previously-dead `tasks` table (added via idempotent `ALTER TABLE` + duplicate-column guard, since SQLite has no `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`) |
| Stale-write detection + atomic writes | `services.py` | SHA256 of the original file content is stored on the proposal at creation time; `apply_write_proposal` re-hashes the current file before writing and rejects if it changed underneath the proposal. The actual write goes through `tempfile.mkstemp` + `os.replace` (atomic on POSIX and Windows) instead of a direct open-and-truncate, so a crash mid-write can't corrupt the target file |
| PPTX indexing | `indexer.py` | Extended the existing `_read_office()` docx/xlsx handling rather than writing a parallel code path; `_read_text()` now returns `(content, parser)` so the DB can track which parser produced which file's content (`files.parser`, `files.parse_status`) |
| Dependency-free fallback UI | `apps/local-ui/` | Copied as-is; it is served automatically by the FastAPI app at `/app/` via a `StaticFiles` mount — no separate process, no build step |

v1's own AST-relation extractor (`ast_extractor.py`, tree-sitter based) was
**not** replaced by v2's older regex version — v1's was strictly better.

**How to verify:** `pytest services/api/tests -q` — 94 tests, including
`test_agent_runtime.py`, `test_office_indexing.py::test_pptx_...`, and the
new `test_stale_write_is_blocked` in `test_core.py`.

## 3. Agents tab in the Next.js Workspace

**Problem:** the agent runtime (section 2) had a full HTTP API but the main
Workspace UI (`apps/web`, what most users actually open) had no way to reach
it — only the fallback `apps/local-ui` did. This was flagged as the #1 "next
step" in the merge report.

**What was built:** a seventh tab, "Agents" (`AgentsView` function in
`Workspace.tsx`), following the exact same pattern as the other six
(Chat/Files/Memory/Graph/Studio/Git): a self-contained function component
that takes `project` as a prop, uses the shared `api()` helper, and reuses
existing CSS conventions (`.status` badges, `.section-heading`, `.inline-form`)
instead of inventing new ones where an existing pattern already fit.

Layout: a left-hand agent roster (the four seeded agents — Coordinator,
Researcher, Worker, Verifier — with their live status), and a main area with
a "queue a task" form (title, instruction, provider) plus a two-column task
list / task detail view. Selecting a task shows its instruction, a
Run/Cancel action bar, and a checkpoint timeline built from
`GET /api/tasks/{id}`'s `events` array (queued → planning → retrieving →
running_tool → verifying → completed/failed/cancelled).

**Why polling, not a websocket/SSE stream:** the task pipeline is
synchronous and short-lived (seconds, not minutes, per the "one heavy engine
at a time" design already used everywhere else in this app), and the rest of
the Workspace has zero streaming infrastructure to hook into. A 2-second
`setInterval` while the task is not in a terminal state (`completed`,
`failed`, `cancelled`) is the same complexity budget as everything else in
this file and stops automatically once the task settles — no cleanup
edge cases, no new dependency.

**Why status badges reuse `.status.applied/.rejected/.pending`:** rather than
inventing a new color system for `queued/planning/retrieving/running_tool/
verifying/waiting_approval`, all in-flight states map to the existing
"pending" (amber) style, `completed` maps to the existing "applied" (green)
style, and `failed`/`cancelled` map to "rejected" (red). This keeps one
consistent status vocabulary across the whole app instead of two.

**What was NOT built:** a UI for creating *custom* agents
(`POST /api/agents`) — the backend supports it, but the Coordinator doesn't
yet delegate to custom agents (documented P1 limitation, same as v2 had it),
so a UI for it would be able to create agents nothing else in the app uses
yet. Added when the Coordinator gains dynamic delegation.

**How to verify:**
1. `npm run typecheck` in `apps/web` → should be clean (it is, verified this session).
2. `npm run dev`, open the Workspace, click "Agents" in the left nav.
3. Queue a task with any instruction, click Run, watch the checkpoint list fill in live.
4. Or, without the UI: `POST /api/tasks` then `POST /api/tasks/{id}/run` then `GET /api/tasks/{id}` and read `events`.

## 4. `INMYAI_*` environment variable prefix bug

**The bug** (flagged in the original audit, confirmed still present in both
v1 and v2 lineage before this fix): `Settings` (in `config.py`) had no
`env_prefix` configured. pydantic-settings without an `env_prefix` only ever
binds the *bare* field name as an env var (e.g. `PROVIDER`), so every
documented `INMYAI_*` override in `.env.example` and the README
(`INMYAI_PROVIDER`, `INMYAI_ALLOWED_ROOTS`, `INMYAI_DATA_DIR`,
`INMYAI_MAX_FILE_MB`, `INMYAI_ALLOW_ANY_LOCAL_PATH`,
`INMYAI_IDLE_MODEL_TIMEOUT_SECONDS`, `INMYAI_WORKSPACE_ROOT`,
`INMYAI_MAX_INDEX_FILES`) silently had **no effect at all**. A user following
the README exactly would set `INMYAI_PROVIDER=ollama` in `.env` and the app
would keep running in Safe Mock mode with no error or warning.

**The fix:** `model_config = SettingsConfigDict(env_file='.env',
env_prefix='INMYAI_', extra='ignore')`. This makes every field bind to its
`INMYAI_<FIELD_NAME>` env var, matching what `.env.example` and the README
already documented.

**The complication:** `.env.example` intentionally documents four fields
*without* the prefix — `OLLAMA_BASE_URL`, `OLLAMA_MODEL`,
`COMFYUI_BASE_URL`, `COMFYUI_WORKFLOW_PATH` — presumably so they line up
with the env var names Ollama's and ComfyUI's own tooling/docs use, for
easier copy-paste between tools. A blanket `env_prefix` would have broken
that by requiring `INMYAI_OLLAMA_BASE_URL` instead.

**Why `validation_alias` per-field instead of renaming those four fields (or
their env vars) to be consistent one way or the other:** it's the smallest
possible change that makes the *existing, already-shipped* documentation
(`.env.example`, the README's Ollama section) correct, with no cascading
edits to docs or any user's existing `.env` file. `validation_alias` reads
the exact string given, ignoring `env_prefix` — confirmed empirically before
writing the fix (see `test_inmyai_prefixed_ollama_variant_is_ignored` in
`test_config.py`, which asserts that setting `INMYAI_OLLAMA_BASE_URL` has
*no* effect, i.e. the alias truly overrides the prefix rather than both
being tried).

**How to verify:** `pytest services/api/tests/test_config.py -v` — three
tests, one for INMYAI_-prefixed fields binding, one for the four
intentionally-unprefixed Ollama/ComfyUI fields still binding bare, one
confirming the prefixed variant of an aliased field is ignored. Or manually:
set `INMYAI_PROVIDER=ollama` in `.env`, start the API, hit
`GET /api/models/status` before this fix (no change) vs after (provider
actually switches).

## 5. `apps/local-ui`: kept permanently, not deprecated

**The question:** now that the Workspace has full agent/task parity with
local-ui, is local-ui still worth maintaining?

**Decision: keep it permanently** as a lightweight fallback surface, not a
stepping stone to delete later.

**Why:**
- It is already a documented, shipped P0 capability (README: "a second,
  dependency-free UI... served by the API itself"), not experimental scaffolding.
- It has effectively zero ongoing maintenance cost: no `node_modules`, no
  build step, no dependency updates, ~3 small files, and it mirrors a stable
  API contract that changes rarely.
- Its exact value proposition showed up unprompted *in this very session*:
  the Next.js production build (`next build`) could not be verified in this
  sandbox because there was no network access to fetch the Next.js SWC
  binary. A Node/npm toolchain problem is precisely the scenario local-ui
  exists for — it needs nothing but the Python backend running.
- It fits InMyAI's own stated design philosophy (8-16 GB laptops, one heavy
  engine at a time, minimal footprint): a UI with no build pipeline and no
  JS framework is the most literal expression of that philosophy available.

**What this means going forward:** Workspace (`apps/web`) stays the primary,
polished, daily-use UI. local-ui stays a functional/ops-style inspector and
emergency fallback — it does not need pixel-parity or feature-parity with
every future Workspace surface, just enough to register a project, run a
task, and read files when the main UI can't be built or run.

**How to verify:** stop the Next.js dev server (or just don't start it),
start only the FastAPI backend, open `http://127.0.0.1:8000/app/` — the
Agents/Files/Knowledge/Studio views should still work end-to-end.

## 6. QA/manifest docs and the new smoke-check script

`QA_REPORT.md` and `FINAL_MANIFEST.md` were carrying test counts and claims
from 2026-07-21 (2 frontend / 8 backend tests, five UI surfaces) that no
longer matched reality after several rounds of work. Rather than hand-edit
the numbers, `SMOKE_REPORT.json` is now produced by a real script,
`scripts/smoke_check.py`, which boots the actual FastAPI `app` object via
`TestClient` (in-process, no port needed) against a throwaway data
directory and exercises the full HTTP surface including the new agent task
pipeline. This makes the smoke report regenerable and honest instead of a
static snapshot someone has to remember to update by hand.

Two things could **not** be re-verified in this sandbox and are called out
explicitly in `QA_REPORT.md` rather than silently left as stale claims:
`next build` (no network access for the SWC binary) and a visual/screenshot
regression pass (Playwright is not installed and cannot be installed here).
Both should be run once on a normal machine.

**How to verify:** `python3 scripts/smoke_check.py` — regenerates
`SMOKE_REPORT.json` and exits non-zero if anything fails.

## 7. Known environment artifacts needing one manual step on your machine

These are all the same underlying cause — this sandbox runs the repo through
a FUSE-mounted filesystem that cannot `unlink()` or overwrite-`rename()`
existing files, only create new ones — and none of them indicate a code
problem:

1. **`.git/index.lock`** at the repo root is stale (left over from very
   early in this multi-session effort). It blocks `git add`/`git commit`
   directly on this checkout. Delete it, then run `git reset --mixed HEAD`
   once — this is safe and non-destructive: it only re-syncs git's internal
   staging index to match `HEAD` and your working files (which already
   match `HEAD` exactly; verified via checksum this session). After that,
   `git status` will show a normal, clean tree.
2. **`probe_test_file.txt`** at the repo root is a leftover empty probe file
   from testing what the sandbox filesystem would allow, from earlier in
   this effort. Safe to delete manually.
3. **`test_git_tools.py`** (9 tests exercising read-only git status/log/
   diff/branch/blame against throwaway fixture repos under
   `.test-runtime/workspace/git-*`) can fail *inside this specific sandbox*
   if an earlier interrupted test run left a stale `index.lock` inside one
   of those fixture repos — the same FUSE limitation as above, just one
   level deeper. It passes cleanly on a normal filesystem (verified via a
   scratch clone in `/tmp` during the merge session: 91/91, then 94/94 after
   this session's additions). If you see it fail after pulling this repo,
   delete `.test-runtime/` and re-run `pytest`.

None of these affect the actual application code — they are all sandbox
bookkeeping.
