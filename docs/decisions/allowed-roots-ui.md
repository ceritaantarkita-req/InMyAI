# Decision record: manage allowed roots from the UI, not by hand-editing `.env`

Date: 2026-07-23
Status: done, verified, committed on `main`

## 1. The problem

Registering a project outside `./workspace` required editing
`INMYAI_ALLOWED_ROOTS` in `.env` and restarting the server - workable for one
developer who wrote the app, impractical for anyone else it's handed to
("kalau gini caranya repot. karena user lain harus ganti2 lewat notepad").
You hit this concretely trying to open a folder from the new Explorer tab:
the same "Path is outside allowed roots" error, twice, with no way to fix it
except leaving the app.

## 2. What was built

Three new endpoints (`GET/POST/DELETE /api/settings/allowed-roots`) backed
by a new `allowed_roots` table, plus a "Allowed folders" section in the
Settings modal to list/add/remove them, and - the part that actually solves
the repeated error you hit - an **"Allow this folder & retry" button that
appears directly inside the registration error itself**, so hitting the
wall and fixing it is one click in the same form instead of a trip to a text
editor and a server restart.

## 3. Why a DB table instead of writing to `.env`

The obvious alternative - have the app rewrite `.env` when a root is added -
was rejected: `.env` is meant to be the static, deploy-time configuration a
human or an installer owns; having the running app silently rewrite it
risks clobbering comments/formatting, fights anyone who manages `.env`
through their own tooling (git-ignored secrets, deployment scripts), and
conflates "what the operator configured" with "what a user clicked" in one
file. A DB table keeps the two cleanly separate: `.env`'s
`INMYAI_ALLOWED_ROOTS` stays authoritative and untouched, while
UI-added roots live in the same local SQLite database everything else in
this app already persists to (projects, memories, tasks, ...) and are
individually removable.

## 4. Why no restart is needed

`resolve_allowed_path` (security.py) already read `settings.allowed_roots`
fresh on every call - it was never cached. So the fix is just keeping that
in-memory string in sync with the DB: `services.sync_allowed_roots()`
rebuilds it from a captured env baseline (`_ENV_ALLOWED_ROOTS`, read once at
process start, before anything mutates it) plus the current `allowed_roots`
DB rows, and is called after every add/remove and once at API startup (to
restore roots added in a previous run). Rebuilding from a fixed baseline
each time - rather than appending/removing substrings from a live string -
was chosen specifically so repeated add/remove cycles can't drift or
duplicate entries.

## 5. What was intentionally left alone

- **Explorer's browsing itself** (`GET /api/browse`) was already exempt from
  the allowed-roots check entirely (see `explorer-and-terminal.md`) - this
  change only makes *registering* a project easier, it doesn't change what
  browsing requires, which was already "nothing."
- **The sensitive-path blocklist** (`BLOCKED_PARTS`) still applies
  unconditionally to `add_allowed_root`, same as every other path-accepting
  endpoint - you can't whitelist your way into `.ssh` or `AppData` through
  this UI either.
- **No bulk-import / "trust everything under X automatically" mode** - each
  added root is an explicit, individually-removable choice, matching how
  `INMYAI_ALLOWED_ROOTS` itself behaves today.

## 6. How to verify

1. `pytest services/api/tests/test_allowed_roots.py -v` - 8 tests: listing
   always includes the workspace root, registering outside an allowed root
   fails until the root is added, the added root shows up with
   `source: "dynamic"`, adding a nonexistent/sensitive path is rejected,
   adding the same root twice is a harmless no-op, removing a root revokes
   access again, and `sync_allowed_roots()` alone (no restart) is enough to
   restore a previously-added root's access.
2. Full regression after this change: 115/115 backend tests, 14/14 frontend
   tests, `tsc --noEmit` clean, `next build` clean.
3. Manually: open Settings, try registering a folder outside the workspace
   root - it fails with the usual message, but now has an "Allow this
   folder & retry" button right there. Click it once; the project registers
   immediately, no `.env` edit, no restart. The folder also now shows up
   under "Allowed folders" in Settings, removable with one click.
