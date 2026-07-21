# InMyAI QA Report

Date: 2026-07-21

## Automated result

| Check | Result |
|---|---|
| Clean `npm ci` from lockfile | PASS |
| Strict TypeScript | PASS |
| Frontend tests | 2/2 PASS |
| FastAPI tests | 8/8 PASS |
| Python compileall | PASS |
| Next.js production build | PASS |
| Next.js production server boot | PASS |
| FastAPI production server boot | PASS |
| API smoke workflow | PASS |
| SQLite FTS search | PASS |
| Memory persistence | PASS |
| Decision supersession | PASS |
| Graph extraction/query | PASS |
| File diff/backup/apply | PASS |
| Local Tesseract OCR | PASS |
| Image workflow simulator | PASS |
| Ollama model-selection heuristic | PASS |
| ComfyUI workflow helper tests | PASS |
| npm production dependency audit | 0 vulnerabilities |
| Python `pip check` | PASS |

## Smoke workflow

See `SMOKE_REPORT.json`. The live local servers were used to verify health, hardware, project listing, incremental indexing, search, Safe Mock chat, source citations, and model-runtime status.

## Visual verification

Reference concept:

- `docs/reference/inmyai-usage-concept.png`

Rendered evidence:

- `docs/qa/workspace-desktop.png` — 1536×1024
- `docs/qa/workspace-mobile.png` — 390×844

Chromium in this environment blocks navigation to all localhost, private-IP, and `file://` URLs with `ERR_BLOCKED_BY_ADMINISTRATOR`. Therefore:

1. live HTTP behavior was verified through API smoke calls and direct HTTP response checks;
2. Playwright Chromium was run under Xvfb;
3. the production CSS and representative application DOM were rendered via `page.set_content` for screenshot comparison;
4. both the accepted concept and rendered screenshots were inspected directly.

## Five visual comparison points

1. **App skeleton:** left project navigation, central workspace, right context rail retained.
2. **Palette:** true white surfaces, quiet gray background, compact dark typography, restrained blue selection state retained.
3. **Chat anatomy:** assistant/user messages, context explanation, source chips, and bottom composer retained.
4. **Safety visibility:** controlled file tools, model/runtime status, RAM profile, and one-engine policy are visible.
5. **Responsive behavior:** desktop sidebars collapse into a five-item mobile bottom navigation without horizontal overflow.

## Above-the-fold copy diff

No unapproved marketing hero, decorative eyebrow, fake metric, or capability claim was added. The implementation uses product-native workspace copy.

## Intentional deviations

- The concept contains seven sidebar utilities. Implementation consolidates them into five primary surfaces; Search is embedded in Files/Graph, Tasks are contextual, and Settings is a modal.
- The concept depicts a finished AI image. Core P0 instead labels the generated preview as a simulator. Real AI generation requires a user-configured local ComfyUI or optional Diffusers model.
- Real Ollama response quality and GPU/VRAM benchmarks were not tested because no local model weights/runtime were available in the build environment.
- Dockerfiles were reviewed but not container-built because Docker is unavailable in the build environment.

## Conclusion

The core source, persistence, retrieval, routing, controlled local file workflow, OCR, Safe Mock orchestration, production builds, and local server startup passed. Absolute freedom from bugs across every Windows driver, Ollama model, ComfyUI workflow, and private repository cannot be guaranteed; provider-specific acceptance testing remains required.
