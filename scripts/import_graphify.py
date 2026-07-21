"""Tolerant Graphify graph.json importer preview.

This script does not write to InMyAI yet. It normalizes common nodes/edges shapes
and prints counts so contributors can inspect a Graphify version before mapping it
into the relations table. Private graph output must never be committed.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def normalize(data: dict) -> tuple[list[dict], list[dict]]:
    graph = data.get('graph', data)
    nodes = graph.get('nodes') or data.get('nodes') or []
    edges = graph.get('links') or graph.get('edges') or data.get('links') or data.get('edges') or []
    if isinstance(nodes, dict):
        nodes = [{'id': key, **(value if isinstance(value, dict) else {'value': value})} for key, value in nodes.items()]
    return list(nodes), list(edges)


def main() -> int:
    if len(sys.argv) != 2:
        print('Usage: python scripts/import_graphify.py graphify-out/graph.json')
        return 2
    path = Path(sys.argv[1])
    data = json.loads(path.read_text(encoding='utf-8'))
    nodes, edges = normalize(data)
    print(json.dumps({'path': str(path), 'nodes': len(nodes), 'edges': len(edges)}, indent=2))
    print('Preview only. See docs/graphify-integration.md for the P1 import contract.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
