// Detects whether this page is running inside the Tauri desktop shell
// (apps/web/src-tauri) rather than a plain browser tab, and - if so - lets
// it use a real native OS folder picker instead of the browser-based
// fallback (InlineFolderBrowser in Workspace.tsx). A plain browser cannot
// do this itself: even the File System Access API's showDirectoryPicker()
// deliberately withholds the actual filesystem path from JavaScript, and
// this app's backend needs a real absolute path, not a sandboxed handle.
// Tauri's webview is not sandboxed the same way, so its dialog plugin can
// hand back a real OS path directly.
//
// `__TAURI_INTERNALS__` is Tauri v2's reliable runtime marker (v1 used
// `__TAURI__`, which may or may not be present in v2 depending on the
// `app.withGlobalTauri` config option) - checked defensively for both so
// this keeps working if that config ever changes.
export function isTauri(): boolean {
  if (typeof window === 'undefined') return false
  const win = window as unknown as Record<string, unknown>
  return '__TAURI_INTERNALS__' in win || '__TAURI__' in win
}

/**
 * Opens the native OS folder picker and returns the chosen absolute path,
 * or null if the user cancelled or this isn't running inside Tauri at all
 * (callers should fall back to the in-browser folder browser in that case).
 */
export async function pickFolderNative(): Promise<string | null> {
  if (!isTauri()) return null
  const { open } = await import('@tauri-apps/plugin-dialog')
  const selected = await open({ directory: true, multiple: false })
  return typeof selected === 'string' ? selected : null
}
