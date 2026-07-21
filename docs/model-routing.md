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

## Limitations

Name-based capability routing is a safe P0 heuristic, not a formal quality benchmark. P1 adds a model registry containing tested capabilities, quantization, measured peak RAM, latency, and evaluation scores per release.
