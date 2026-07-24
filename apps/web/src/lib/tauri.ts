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

/**
 * Opens a native OS *file* picker (as opposed to `pickFolderNative`'s
 * directory picker) and returns the chosen absolute path, or null if
 * cancelled or not running inside Tauri. Used by Chat's Attach button so a
 * user can reference any file on disk - a document, image, archive,
 * whatever - not just files already indexed into the active project.
 *
 * Deliberately does NOT read the file's content: only Insert (which reads
 * through `/api/projects/{id}/file`, scoped to files already inside an
 * indexed, allowed project) can guarantee content is actually sent to the
 * model. A path picked here that lives outside any allowed root is still
 * just a text reference in the message - the backend's access-control
 * policy (the same one behind "allowed roots" in Settings) is not
 * bypassed by this picker, on purpose.
 */
export async function pickFileNative(): Promise<string | null> {
  if (!isTauri()) return null
  const { open } = await import('@tauri-apps/plugin-dialog')
  const selected = await open({ directory: false, multiple: false })
  return typeof selected === 'string' ? selected : null
}

/**
 * Shows a Yes/Cancel confirmation dialog. Inside Tauri, the webview
 * intercepts the browser's own `window.confirm()` and routes it through an
 * IPC command that doesn't exist for this dialog plugin version, throwing
 * "dialog.confirm not allowed. Command not found" instead of ever showing a
 * dialog - the same class of gap as the native folder picker: Tauri's
 * webview isn't a plain browser, so browser-only APIs that happen to also
 * exist as globals can still silently misbehave. The fix is the same
 * pattern as `pickFolderNative()`: use the dialog plugin's own `confirm()`
 * JS function (which goes through the plugin's real, permitted IPC command)
 * when running inside Tauri, and fall back to the browser's native
 * `window.confirm()` everywhere else.
 */
export async function confirmDialog(message: string, title = 'InMyAI'): Promise<boolean> {
  if (isTauri()) {
    const { confirm } = await import('@tauri-apps/plugin-dialog')
    return confirm(message, { title, kind: 'warning' })
  }
  return window.confirm(message)
}
