# Automatic Model and Tool Routing

## Goal

Select the least expensive engine that can correctly perform the task.

## P0 classification

- OCR → Tesseract/pypdf
- image request → image router
- diff → deterministic diff
- graph/dependency → graph retrieval, then optional small LLM explanation
- memory/decision → structured retrieval, then optional small LLM explanation
- coding → local coding-capable LLM
- general → local general LLM

## Ollama model selection

InMyAI reads installed Ollama models. For coding tasks it prefers names containing `coder`, `code`, `devstral`, or `starcoder`. For general, memory, and graph explanation tasks it prefers common general model families. Within a matching family, the smallest installed model is chosen first.

Users can still request a specific installed model.

## Transparency

Every chat response includes:

- detected task
- selected engine
- selected provider
- selection reason
- estimated RAM class
- context token budget

## Model registry

When `models/registry.json` exists, selection prefers a profile whose
`task_types` contain the detected task, whose `hardware_profile` matches the
device (`lite` < 12 GB total / `standard` otherwise), and whose `model` is
installed in Ollama. Verified profiles rank above unverified within a match
set; the smallest `peak_ram_mb` wins ties. The shipped default registry is
`verified: false` — measure peak RAM, latency, and quality on your hardware
before flipping a profile to `verified: true`.

If no profile matches (empty registry, mismatched hardware, model not
installed), selection falls back to the name-heuristic, then to the configured
default model. Override the registry path with `INMYAI_MODEL_REGISTRY_PATH`.

## Limitations

The registry ships with example profiles only (`verified: false`). Absolute
quality claims still require the user to benchmark each model on their own
hardware. Name-based capability routing remains the fallback heuristic, not a
formal quality benchmark.
