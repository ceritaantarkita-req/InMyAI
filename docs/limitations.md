# Limitations

- The system cannot be guaranteed bug-free on every device, model, runtime, driver, or project.
- Safe Mock verifies orchestration but is not a generative model.
- Real image generation is optional and was not bundled or model-quality tested.
- P0 code graph extraction is intentionally basic compared with Graphify.
- P0 does not execute terminal commands.
- P0 does not use a native Tauri sandbox.
- PDF OCR handles extractable text; scanned PDF page rendering for OCR is not yet included.
- FTS retrieval is lexical; embeddings are optional future work.
- Automatic model routing currently uses task heuristics and installed model names/sizes, not a full benchmark registry.
- No encryption-at-rest or multi-user authentication is included.
- A 2B–4B local model will not match a large cloud model on every reasoning or coding task.
