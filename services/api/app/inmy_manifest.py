from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path


_MANIFEST_PATH = Path(__file__).resolve().parents[3] / 'inmy.manifest.json'


@lru_cache(maxsize=1)
def load_inmy_manifest() -> dict:
    parsed = json.loads(_MANIFEST_PATH.read_text(encoding='utf-8'))
    if parsed.get('schemaVersion') != '1.0.0':
        raise RuntimeError('Unsupported InMy manifest schema version')
    if parsed.get('canonicalId') != 'inmyai':
        raise RuntimeError('InMy manifest canonical identity mismatch')
    return parsed
