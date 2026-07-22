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

## Importer

The CLI importer maps a Graphify graph.json into InMyAI's `relations` table:

```bash
python scripts/import_graphify.py graphify-out/graph.json --project 3
```

Edges are inserted with `confidence='INFERRED'` so Graphify provenance stays
distinct from the deterministic `EXTRACTED` relations produced by indexing.
The import is idempotent: re-running on the same graph adds no duplicate rows.
Aggregate counts are printed and recorded in the audit log; graph node/edge
identifiers are never echoed (they may be private project knowledge).

## Integration contract

The importer maps Graphify nodes and edges into InMyAI's `relations` table while preserving:

- source node
- relationship
- target node
- evidence
- `EXTRACTED` or `INFERRED` confidence tag

Graphify is a graph-memory source. It does not replace the decision ledger, user preferences, project task state, or consent policy.
