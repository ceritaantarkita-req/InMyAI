# Decision record: Tauri desktop shell (first pass - dev mode + native folder picker)

Date: 2026-07-24
Status: **confirmed working on Windows** - `cargo tauri dev` compiled
cleanly (~2 minutes first run) and opened a real native `InMyAI` window.
One follow-up bug found and fixed during that first run: see section 7.

## 1. The problem

You asked, after hitting the browser's folder-typing friction twice: "kalau
gini caranya lebih tepat gue bikin aplikasi local dong ya?" This was already
a known gap - `docs/roadmap.md` has listed "Tauri desktop shell and native
folder picker" as an unbuilt P1 item since early in this project, for
exactly this reason. Today's Settings improvements (inline browser, allowed
folders UI) reduce the friction; a real native folder picker removes the
underlying cause instead of working around it.

## 2. What "local" already meant, and what a desktop shell actually changes

InMyAI's backend and data were already 100% local before this - nothing
about this change makes it "more local" in a privacy or data-location
sense. What changes is the *delivery mechanism*: today you run
`npm run dev` in a terminal and open `localhost:3000` in a browser tab;
after this, there's a real `InMyAI.exe` you can pin to the Start Menu, and
its window's file dialogs are genuine OS dialogs instead of a web page's
approximation of one.

Tauri was chosen over Electron for the same reason the rest of this app
favors small footprints: Tauri uses the OS's own web renderer (WebView2 on
Windows, already built into Windows 10/11) instead of bundling an entire
Chromium copy per app, so the resulting binary and memory footprint are a
small fraction of an equivalent Electron app - consistent with this
project's "everyday 8-16 GB laptop" design constraint.

## 3. Scope of this pass: dev mode + folder picker only, not production packaging yet

**What's included:**

- `apps/web/src-tauri/` - a minimal Tauri v2 project (`Cargo.toml`,
  `tauri.conf.json`, `main.rs`, `build.rs`, placeholder icons) configured so
  `cargo tauri dev` runs the repo root's existing `npm run dev` (which
  already starts both the FastAPI backend and the Next.js dev server -
  `scripts/dev.mjs`, unchanged) and opens a native window pointing at
  `http://127.0.0.1:3000` once it's reachable.
- `tauri-plugin-dialog` (Rust) + `@tauri-apps/plugin-dialog` (JS): a real
  native folder-picker dialog.
- `apps/web/src/lib/tauri.ts`: `isTauri()` detects whether the page is
  running inside this shell versus a plain browser tab;
  `pickFolderNative()` opens the OS dialog and returns a real absolute
  path, or `null` if not running inside Tauri (or if the user cancelled).
- Wired into the two places path-typing friction showed up: the "Browse…"
  button in Settings' "Add a local project" form, and a new "Browse…"
  button in the Explorer toolbar (shown only when `isTauri()` is true,
  since the plain-browser version already has its own path input and the
  inline HTML folder browser - see `allowed-roots-ui.md`).

**What's deliberately deferred to a follow-up pass**, because it's a
meaningfully larger, separate body of work:

- **Production bundling** (a real installer `.msi`/`.exe` someone else can
  double-click to install): `tauri.conf.json`'s `frontendDist` points at
  `apps/web/out`, which would need Next.js configured for static export
  (`output: 'export'`) and a real `beforeBuildCommand` - not done yet.
- **Bundling the Python backend** so an end user doesn't need Python/Node
  installed at all (a Tauri "sidecar" binary, typically built with
  PyInstaller). Right now `cargo tauri dev` still relies on your existing
  `.venv` and Node install, exactly like `npm run dev` does today - this
  pass only changes *how the window opens*, not what it depends on.
- **Code signing / distribution** for handing a built app to someone else
  without Windows SmartScreen warnings.

Rationale for stopping here: the concrete pain point you raised was the
folder picker specifically, and that's fully solved by this pass without
first solving the much larger "ship a zero-dependency installer to a
stranger" problem, which deserves its own dedicated pass (and its own
decision about code signing, update mechanism, etc.) rather than being
rushed alongside everything else already shipped today.

## 4. What was actually verified, and what couldn't be

This sandbox has no Rust/Cargo toolchain and no way to produce or run a
Windows binary regardless (no WebView2, no Windows). What **was** verified
here, since none of it depends on Rust:

- `npm install` succeeds with the new `@tauri-apps/api`,
  `@tauri-apps/plugin-dialog`, `@tauri-apps/cli` dependencies.
- `tsc --noEmit` is clean with the new `lib/tauri.ts` and its two call
  sites.
- All 14 frontend tests still pass.
- `next build` still succeeds (verified the same way as every other
  frontend change this session - built from an `/tmp` copy, since building
  directly on this sandbox's mounted folder hits an unrelated `Bus error`
  mmap artifact, see `explorer-and-terminal.md` section 7).
- `tauri.conf.json`, `package.json`, and `Cargo.toml` are all valid
  JSON/TOML.
- The generated icons (`apps/web/src-tauri/icons/`) are real, valid
  multi-size PNG/ICO files (placeholder artwork - a simple rounded square
  with a dot, loosely echoing the app's existing logo mark - swap for real
  branding whenever you have it, via `npx tauri icon <path-to-a-1024px-png>`
  from `apps/web`, which regenerates every required size automatically).

What could **not** be verified here and needed your machine: whether
`cargo tauri dev` actually compiles and opens a working native window.
**Confirmed working**: first run took ~2 minutes to compile all Rust
dependencies, then opened a real `InMyAI` window with the app's UI visible
inside it - exactly as designed. One real bug turned up at that point
(client-side JS wasn't executing inside the window), fixed in section 7.

## 5. Exact steps to try this on your machine

```powershell
cd "C:\Users\Amand\.gemini\antigravity\scratch\ideagentics\demo\InMyAI_FullStack"

# 1. Rust toolchain (skip if `rustc --version` already works)
winget install -e --id Rustlang.Rustup
# then open a NEW PowerShell window so PATH picks up cargo/rustc

# 2. Tauri's Windows build requirement: the C++ build tools (skip if you
#    already have Visual Studio or "Build Tools for Visual Studio" with the
#    "Desktop development with C++" workload installed)
winget install --id Microsoft.VisualStudio.2022.BuildTools --override "--passive --wait --add Microsoft.VisualStudio.Workload.VCTools;includeRecommended"

# 3. Pull in the new JS dependencies (@tauri-apps/*) added this session
npm install

# 4. First run - this compiles the Rust side (slow the first time, a few
#    minutes; fast on subsequent runs) and should open a native InMyAI
#    window with your existing app inside it
npm run desktop:dev
```

Once it opens: go to Settings -> "Add a local project" -> click
**Browse…** - it should now pop a real Windows folder-picker dialog instead
of the in-page browser, and picking a folder there hands back a real
`C:\...` path directly, no typing at all. Same for the new **Browse…**
button in the Explorer toolbar.

If `cargo tauri dev` fails at this first attempt, paste the exact error and
we'll debug it together - environment setup (missing build tools, PATH
issues, etc.) is the most likely first-run snag, not the Tauri config
itself.

## 6. How to verify what doesn't need Rust

```powershell
npm run typecheck:web
npm run test:web
```

Both should pass exactly as they did before this change - this pass adds a
new, additive capability without touching any existing behavior in the
plain-browser mode.

## 7. Bug found on first real run: the window opened, but nothing was clickable

**Symptom:** the native window opened and rendered the full Chat/Files/...
UI correctly, but every button (including "Add project") was unresponsive.
The dev-server terminal showed the actual cause:

```
Blocked cross-origin request to Next.js dev resource /_next/webpack-hmr
from "127.0.0.1". Cross-origin access to Next.js dev resources is
blocked by default for safety.
```

**Root cause:** Next.js's dev server blocks cross-origin requests to its
own dev assets (webpack-hmr, JS chunks) by default, as a DNS-rebinding
protection. A plain browser tab navigating to `http://127.0.0.1:3000`
satisfies this check trivially; Tauri's webview loading that same URL
(`tauri.conf.json`'s `devUrl`) apparently doesn't present as the same
origin to Next's check, so it got blocked - which silently prevented
React from ever finishing hydration. The page painted (server-rendered
HTML is always sent regardless), but no client-side JS ever attached, so
nothing was clickable. Exactly the kind of bug that's invisible without
actually running it, which is why section 4 flagged this specific gap
honestly instead of assuming success from config review.

**Fix:** added `allowedDevOrigins: ['127.0.0.1', 'localhost']` to (a
previously nonexistent, now added) `apps/web/next.config.mjs`, exactly as
Next.js's own error message instructed. Doesn't affect the plain-browser
path at all - it only widens which origins are trusted for dev assets,
verified via `tsc --noEmit`, all 14 frontend tests, and a clean `next
build`, then confirmed live in the desktop shell itself.

**New files/folders from this first run, now tracked appropriately:**
`apps/web/src-tauri/Cargo.lock` is committed on purpose (this is an
application, not a library - a locked dependency tree is wanted, matching
Tauri's own project template convention). `apps/web/src-tauri/gen/schemas/`
(auto-regenerated capability/ACL JSON on every build) and `target/` (Rust
build output) are gitignored, also matching Tauri's own template.

## 8. Second bug found immediately after: "dialog.open not allowed"

**Symptom:** with section 7's fix in place, the UI became fully clickable
(confirmed: Settings modal, Allowed folders section, etc. all worked) - but
clicking "Browse…" threw `dialog.open not allowed. Permissions associated
with this command: dialog:allow-open, dialog:default`.

**Root cause:** Tauri v2 gates every plugin command behind an explicit,
per-window capability/permission grant (its ACL system) - and the initial
hand-written scaffold in this session (Cargo.toml/tauri.conf.json/main.rs)
never created a `capabilities/` file at all, so the main window had no
permissions granted beyond whatever Tauri's absolute baseline default is -
not enough to call `dialog.open`. This is the one piece the normal
`npm create tauri-app` scaffolding tool would have generated automatically
that hand-writing the config from scratch skipped.

**Fix:** added `apps/web/src-tauri/capabilities/default.json`, granting the
`main` window `core:default` (baseline app capabilities) and
`dialog:default` (everything the dialog plugin exposes, including `open`) -
exactly the two permission identifiers the error message itself named as
acceptable. Tauri auto-loads every JSON file under `capabilities/`, no
change to `tauri.conf.json` needed.

**Needs a restart, not just a page reload:** capabilities are compiled into
the binary by `tauri-build` at build time, not read live from disk - after
pulling this fix, stop `npm run desktop:dev` (Ctrl+C) and start it again.
It should be much faster than the very first run (only the capability
manifest changed, not the Rust dependency tree), and "Browse…" should then
open a real Windows folder dialog.
