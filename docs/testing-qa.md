# Testing and QA

## Automated checks

```bash
npm run qa
```

Coverage includes:

- strict web TypeScript
- five-surface navigation invariant
- API health and hardware snapshot
- project registration and incremental index
- FTS search
- relation graph extraction/query
- memory persistence
- decision supersession
- write proposal, diff, backup, apply
- real local Tesseract OCR where available
- image simulator artifact creation
- Safe Mock chat with citations
- task-aware Ollama model selection
- Next.js production build

## Manual checks

- desktop 1536×1024
- laptop 1280×800
- mobile 390×844
- add project and index
- Safe Mock chat
- Ollama disconnected state
- file proposal/reject/apply
- decision replacement
- graph node inspection
- OCR with clean and poor scans
- reduced-motion preference

## Provider acceptance tests

Real model output quality, token speed, peak RAM, VRAM, and image generation must be benchmarked on target hardware. CI intentionally does not download weights.
