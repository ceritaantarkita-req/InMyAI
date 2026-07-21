# Graphify Integration

InMyAI includes a small deterministic graph so the core works independently. Graphify can enrich this graph with deeper code, document, PDF, image, video, and cross-file relationships.

## Recommended workflow

```bash
uv tool install "graphifyy[ollama]"
graphify install --project --platform codex
graphify .
```

Expected output:

```text
graphify-out/
├── graph.html
├── GRAPH_REPORT.md
└── graph.json
```

`graphify-out/` is ignored by Git because it may contain private project knowledge.

## Integration contract

P1 importer maps Graphify nodes and edges into InMyAI's `relations` table while preserving:

- source node
- relationship
- target node
- evidence
- `EXTRACTED` or `INFERRED` confidence tag

Graphify is a graph-memory source. It does not replace the decision ledger, user preferences, project task state, or consent policy.
