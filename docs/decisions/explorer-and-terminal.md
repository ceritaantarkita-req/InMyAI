# Decision record: Explorer (mind-map browser) and Terminal tabs

Date: 2026-07-23
Status: done, verified, committed on `main`

Same purpose as `v1-v2-merge-and-agents-panel.md`: what the problem was,
what was built, why, what else was considered, and how to check it yourself.

## 1. The problem

You wanted to point InMyAI at a whole folder of many unrelated projects
(`ideagentics`) and explore it before deciding what to register — without
InMyAI trying to read/index everything at once, and without hitting the
"Path is outside allowed roots" wall just to *look around*. Your own
description: root = `ideagentics`, sub-folders shown as connected dots,
clicking a dot reveals its own sub-folder dots — "kaya graphify", "semacem
mind maps" — plus a floating bar showing the full path of whatever's
selected. You also asked where chat fits relative to this, whether the left
nav stays put, and asked for a real terminal ("kaya powershell") so you
don't have to keep switching windows.

Three clarifying questions were asked and answered before building:

1. **Drill-down depth** — answered "Bebas sampai ke file": navigation goes
   all the way down to individual files, not just to project folders.
2. **Terminal type** — answered "kaya powershell maksud gue": a real
   interactive shell, not a simple one-shot command runner.
3. **Security model for browsing** — answered "Lihat nama folder bebas
   dulu": folder/file *names* can be browsed freely without pre-whitelisting
   a root; only actually opening/indexing a folder as a project still
   requires `INMYAI_ALLOWED_ROOTS`.

## 2. Where chat fits (the navigation answer)

Explorer and Terminal became two new tabs alongside the existing seven
(Chat/Files/Memory/Graph/Studio/Git/Agents), in the same left-hand nav, same
position — nothing moved. Explorer is a *discovery* surface: browse anywhere
on disk, then hand a chosen folder to Chat via "Open as project", which
registers it and switches you straight into Chat with that project active.
Terminal is an *execution* surface that works independently of any
registered project. This keeps one consistent mental model: Explorer finds,
Terminal runs, Chat/Files/Memory/Graph/Studio/Git/Agents work *within* a
project once one is open.

**Why this split instead of merging browsing into the existing project
picker:** the existing picker already assumes you know the exact path and
just need to confirm it's allowed. Explorer solves a different problem —
you don't yet know which of many folders you want — so it deliberately does
not require a project to exist first, unlike every other tab except
Terminal.

## 3. Security model: browsing is free, opening is gated

**New function, `resolve_browsable_path` (`security.py`), used only by
`GET /api/browse`:** resolves and validates the path exists and is a
directory, and still unconditionally enforces the sensitive-path blocklist
(`BLOCKED_PARTS` — things like `.git/config` secrets, `.ssh`, credential
files), but **deliberately skips** the `INMYAI_ALLOWED_ROOTS` check that
`resolve_allowed_path` enforces everywhere else (project registration, file
reads/writes, indexing).

**Why this split is safe:** `/api/browse` only ever returns names, types
(file/dir), and whether a directory looks like a project — it never reads
file *contents*. Registering a project (`POST /api/projects`) and every
content-touching endpoint still goes through the original
`resolve_allowed_path` and is refused with the same "outside allowed roots"
error as before if the root isn't whitelisted. So browsing being free
doesn't change what InMyAI can actually read, index, or write — it only
changes whether you can *see folder names* before deciding to allow one in.

**Test proving this,** `test_browse_works_without_allowlisting` in
`test_browse.py`: with `INMYAI_ALLOWED_ROOTS` empty, `GET /api/browse` on an
arbitrary outside folder returns 200, while `POST /api/projects` on that
same folder still returns 400 "outside allowed roots" — confirming the two
checks are genuinely independent, not that the gate was accidentally
removed everywhere.

**`looks_like_project(path)`:** a directory is flagged `is_project: true` in
the browse response if it directly contains a marker file (`.git`,
`package.json`, `pyproject.toml`, `requirements.txt`, `go.mod`,
`Cargo.toml`). This is a display hint only (Explorer highlights these dots
differently) — it has no effect on what can be opened; any folder, project
or not, can be sent to "Open as project".

**How to verify:** `pytest services/api/tests/test_browse.py -v` (8 tests).

## 4. Explorer frontend: hand-rolled radial mind-map, not a graph library

**What was built:** `ExplorerView` in `Workspace.tsx` — no new dependency.
Positions are computed directly with basic trigonometry (each visible
sibling placed evenly around a circle centered on its parent), rendered as
plain SVG circles/lines/text. Clicking a directory dot re-fetches
`/api/browse` for that path and re-centers the view one level deeper;
clicking a file dot selects it (no further drill-down, since files have no
children) — satisfying "bebas sampai ke file" without needing separate
file-vs-folder logic. A back button and an in-memory history stack support
retreating up the tree. The last-browsed root is remembered in
`localStorage` (`inmyai:explorer:lastRoot`) so re-opening Explorer doesn't
always restart at nothing.

**Why not add a graph-layout library (e.g. d3-force, react-flow):** the
requested visual — one ring of children around one clicked parent,
one level visible at a time — doesn't need force simulation, physics, or
a general graph layout engine; those solve a harder problem (arbitrary
graphs with cycles, many simultaneous nodes) than "N siblings evenly spaced
around a circle." A ~30-line trigonometry helper is easier to reason about,
has zero new dependencies to keep patched, and matches how the rest of this
codebase already draws its one other graph-like view (the code-relation
Graph tab also avoids a graph library).

**The floating path bar:** a fixed bar at the bottom of the Explorer canvas
shows the full absolute path of whatever's currently selected (exactly the
`C:\Users\...\CODE_OF_CONDUCT.md`-style path you asked for), with a Copy
button and an "Open as project" button. "Open as project" is available for
*any* selected directory, not just ones flagged `is_project` — since a
non-marker folder (e.g. a plain folder of notes) is still a legitimate
thing to register and chat about.

**How to verify:** `npm run dev`, click "Explorer" in the left nav, browse
down into a real folder, click a file, confirm the path bar shows its full
path, click "Open as project" on a folder and confirm it switches you into
Chat with that project active.

## 5. Terminal: real PTY, not a command-runner

**Why a real PTY instead of a simple "run one command, return output"
endpoint:** you specifically said "kaya powershell maksud gue" — a
persistent interactive session (cd, environment state, running programs
that prompt for input, Ctrl+C, etc.), which a stateless
run-command-return-output endpoint cannot provide. That requires an actual
pseudo-terminal process, not a subprocess.run() wrapper.

**Architecture** (`terminal.py`, new): `PtySession` wraps either the
`pywinpty` package's `PtyProcess` (Windows, via ConPTY) or POSIX
`pty.fork()` (Linux/macOS), behind one shared interface: `.read()`,
`.write()`, `.resize(cols, rows)`, `.close()`. `pywinpty` is listed in
`requirements.txt` with an environment marker
(`pywinpty==2.0.15; sys_platform == 'win32'`) so `pip install` on
Linux/macOS doesn't even attempt to fetch a Windows-only package.

**Transport:** `WS /ws/terminal?path=<cwd>` — a FastAPI WebSocket. Frontend
sends JSON text frames (`{type:'input',data}` on every keystroke,
`{type:'resize',cols,rows}` on container resize); backend streams raw PTY
output back as binary frames, and sends JSON `{type:'error'|'exit', ...}`
for session lifecycle events. Binary framing for output (rather than JSON-
wrapping every chunk) avoids a base64-encoding tax on what can be a lot of
terminal output.

**Why the shell process's blocking reads run via
`loop.run_in_executor`:** `os.read()` on a PTY file descriptor blocks the
calling thread until output is available; running it directly on the
asyncio event loop would freeze every other request the API is handling.
Offloading it to the default thread-pool executor keeps the rest of the API
responsive while a terminal session is open. `session.close()` in the
relay's `finally` block runs *synchronously*, not via the executor —
`os.kill`/`os.close` are fast, non-blocking syscalls, and routing them
through a thread pool that might already be saturated by other blocked
`os.read()` calls risked cleanup never getting scheduled, leaving orphaned
processes. This was found and fixed during testing (see below).

**Explicit non-sandboxing:** the Terminal tab shows a permanent warning
("Not sandboxed — this is a real shell under your own account") because
it deliberately bypasses every one of InMyAI's own file-access policies
(`BLOCKED_PARTS`, `INMYAI_ALLOWED_ROOTS`) — it's your OS shell, full stop.
This was a conscious choice, not an oversight: building a *restricted*
shell would not satisfy "kaya powershell", and a fake sense of sandboxing
would be worse than an honest warning.

**How to verify (needs your real machine — a live shell process can't run
inside this sandbox in a meaningful end-to-end way):**
1. Windows: `.venv\Scripts\python.exe -m pip install -r services\api\requirements.txt` (installs `pywinpty`). Linux/macOS: no extra step, POSIX `pty` is stdlib.
2. `npm install` in `apps/web` (installs `@xterm/xterm` and `@xterm/addon-fit`, already in `package.json`).
3. `npm run dev`, click "Terminal" in the left nav — you should get a live shell prompt (PowerShell on Windows, your default shell on POSIX). Try `cd`, run something that keeps state (e.g. `set FOO=bar` then `echo %FOO%` on Windows), resize the window, confirm the shell keeps working.

## 6. Why `test_terminal.py` unit-tests `PtySession` directly instead of testing through the WebSocket

While building this, stacking 2-3 real PTY-backed WebSocket sessions
through FastAPI's `TestClient.websocket_connect()` in one test process
produced intermittent hangs — not on the same test each run, and a
standalone script proving the raw `pty.fork()` + resize logic works
perfectly outside of asyncio/TestClient. This points to `TestClient`'s
sync-to-async bridge (a "portal" thread) getting into a bad state under
multiple concurrent blocking PTY sessions, not a bug in the PTY code
itself — real `uvicorn` doesn't share that bridge.

Rather than fight a test-harness artifact, `test_terminal.py` was rewritten
to unit-test the `PtySession` class directly — spawn a session, write a
command, read the echoed output, resize it, close it — which is fast
(under 1 second), 100% reliable across repeated runs, and still exercises
every real code path except the WebSocket framing glue itself. That glue is
covered instead by the manual end-to-end check in section 5, since it
genuinely needs a real terminal on a real machine to mean anything.

**How to verify:** `pytest services/api/tests/test_terminal.py -v` (5 tests).

## 7. The Next.js SSR crash, and the actual fix

`@xterm/xterm` reads browser-only globals (`self`) the moment its module is
evaluated. Even inside a `'use client'` component, Next.js still
server-renders client components once for the initial HTML — so a plain
top-level `import { Terminal } from '@xterm/xterm'` anywhere in
`Workspace.tsx` got pulled into the server bundle and crashed `next build`
with `ReferenceError: self is not defined`.

**Fix:** `TerminalView` was moved into its own file
(`components/TerminalView.tsx`) and is loaded from `Workspace.tsx` only via
`next/dynamic(() => import('./TerminalView').then(m => m.TerminalView),
{ ssr: false })`. The file split matters as much as `ssr: false` does —
dynamic import needs a real module boundary to lazily load, it can't defer
loading part of an already-imported file.

**How this was actually confirmed fixed** (not just reasoned about):
`next build` was run twice — once reproducing the crash with the old
top-level import (confirmed via an earlier accidental real build in this
project's history), and once after this fix, on a filesystem copy outside
the FUSE-mounted project folder (building directly on the mounted folder in
this sandbox hits an unrelated `Bus error` — an mmap artifact of this
sandbox's mounted filesystem, not a Next.js or code issue; rsyncing the
`apps/web` folder into a normal `/tmp` path and building there avoids it
entirely and matches what your own machine's real filesystem will do).
Result: clean build, static pages generated, no SSR error.

**How to verify:** `npm run build` in `apps/web` on your machine should
finish with `Generating static pages ... ✓` and no `self is not defined`
error.

## 8. Full regression after both features

- Backend: `pytest services/api/tests -q` → 107 passed (94 prior + 8 browse + 5 terminal, replacing net new).
- Frontend: `node --test tests/*.test.mjs` → 14 passed.
- `tsc --noEmit` → clean.
- `next build` → clean (see section 7 for where/how this was actually run).

## 9. What was intentionally not built

- **Multi-select or bulk actions in Explorer** (e.g. registering several
  folders at once) — out of scope for "let me look around and open one at a
  time"; add if a real need for batch registration shows up.
- **Terminal session persistence across tab switches** — closing the
  Terminal tab currently ends the shell session (the WebSocket closes on
  unmount). Keeping a shell alive in the background while you're in another
  tab is a reasonable future ask but adds real complexity (session
  registry, reconnect-to-existing-session protocol) that wasn't part of
  what you described.
- **Explorer thumbnails/previews** — the mind-map shows names and a
  file/folder/project distinction only; opening actual file contents still
  goes through Chat/Files once a project is registered.
