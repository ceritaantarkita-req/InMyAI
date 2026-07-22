"""Graphify graph.json importer CLI.

Maps a Graphify graph.json into InMyAI's relations table for a registered
project. Imported edges are tagged confidence='INFERRED' so they supplement
(but do not replace) the deterministic EXTRACTED relations produced by
indexing. The import is idempotent: re-running on the same graph adds no
duplicate rows.

Usage:
    python scripts/import_graphify.py graphify-out/graph.json --project 3

The graph file is read locally and never echoed to stdout beyond aggregate
counts, because graphify-out/ may contain private project knowledge.

See docs/graphify-integration.md for the integration contract.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.api.app import services  # noqa: E402
from services.api.app.config import settings  # noqa: E402
from services.api.app.database import migrate  # noqa: E402


def _load_graph(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except OSError as exc:
        raise SystemExit(f'Could not read {path}: {exc}') from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(f'{path} is not valid JSON: {exc}') from exc


def main() -> int:
    parser = argparse.ArgumentParser(description='Import a Graphify graph.json into InMyAI relations.')
    parser.add_argument('graph', type=Path, help='Path to graph.json produced by `graphify .`')
    parser.add_argument('--project', type=int, required=True, help='Registered InMyAI project id')
    parser.add_argument('--data-dir', type=Path, default=None, help='Override INMYAI_DATA_DIR for this run')
    args = parser.parse_args()

    if not args.graph.exists():
        print(f'Graph file not found: {args.graph}', file=sys.stderr)
        return 2
    if args.data_dir is not None:
        settings.data_dir = args.data_dir

    migrate()
    graph_data = _load_graph(args.graph)

    try:
        result = services.import_graphify(args.project, graph_data)
    except KeyError:
        print(f'Project id {args.project} not found. Register it first via the UI or /api/projects.', file=sys.stderr)
        return 2
    except Exception as exc:  # pragma: no cover - defensive
        print(f'Import failed: {exc}', file=sys.stderr)
        return 1

    print(json.dumps({
        'project_id': args.project,
        'graph': str(args.graph),
        'nodes': result['nodes'],
        'edges': result['edges'],
        'imported': result['imported'],
        'skipped': result['skipped'],
    }, indent=2))
    print('Import complete. Imported edges are tagged INFERRED and supplement indexed relations.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
