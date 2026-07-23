// InMyAI desktop shell: a thin native window around the existing local
// Next.js frontend + FastAPI backend (see beforeDevCommand in
// tauri.conf.json, which starts both via the repo root's `npm run dev`).
// Nothing about InMyAI's actual functionality lives here - this is
// packaging only. The one real capability this adds over the plain
// browser tab is a genuine OS folder picker (tauri-plugin-dialog), which
// browsers cannot expose a real filesystem path from at all.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .run(tauri::generate_context!())
        .expect("error while running the InMyAI desktop shell");
}
