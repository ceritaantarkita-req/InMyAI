"""Model benchmark registry and selection.

Augments (does not replace) the legacy name-heuristic model selection. When a
user ships a `models/registry.json` with measured profiles, `select_model`
prefers a profile whose task_type and hardware_profile match the current
request and whose model is actually installed in Ollama. If no profile
matches, it falls back to the name-heuristic, and finally to the configured
default model.

The registry is loaded lazily and cached for the process; the path is
configured via `INMYAI_MODEL_REGISTRY_PATH` (see config.py). Missing or
corrupt registry files degrade gracefully to the heuristic — the core always
runs, even before the user has measured anything.

Profile JSON shape (see models/registry.example.json):
  {
    "schema_version": 1,
    "profiles": [
      {
        "id": "general-small",
        "runtime": "ollama",
        "model": "gemma3:4b",
        "task_types": ["general", "memory", "graph"],
        "hardware_profile": "standard",   # "lite" | "standard"
        "peak_ram_mb": 3000,              # optional, informational
        "verified": false,                # optional, default false
        "notes": "..."                    # optional
      }
    ]
  }
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import settings


@dataclass
class ModelProfile:
    id: str
    runtime: str
    model: str
    task_types: list[str]
    hardware_profile: str
    peak_ram_mb: int | None = None
    verified: bool = False
    notes: str = ''


# ---- loading (cached) ----

_registry_cache: tuple[Path, list[ModelProfile]] | None = None


def _profile_from_dict(raw: dict) -> ModelProfile | None:
    try:
        return ModelProfile(
            id=str(raw['id']),
            runtime=str(raw.get('runtime', 'ollama')),
            model=str(raw['model']),
            task_types=[str(t) for t in raw.get('task_types', [])],
            hardware_profile=str(raw.get('hardware_profile', 'standard')),
            peak_ram_mb=int(raw['peak_ram_mb']) if raw.get('peak_ram_mb') is not None else None,
            verified=bool(raw.get('verified', False)),
            notes=str(raw.get('notes', '')),
        )
    except (KeyError, TypeError, ValueError):
        return None


def load_registry(path: Path | None = None) -> list[ModelProfile]:
    """Load and validate the registry file. Missing/corrupt → [] (never raises)."""
    target = Path(path) if path is not None else settings.model_registry_path
    if not target.exists():
        return []
    try:
        data = json.loads(target.read_text(encoding='utf-8'))
    except (json.JSONDecodeError, OSError):
        return []
    raw_profiles = data.get('profiles', []) if isinstance(data, dict) else []
    profiles: list[ModelProfile] = []
    for raw in raw_profiles:
        if isinstance(raw, dict):
            profile = _profile_from_dict(raw)
            if profile is not None:
                profiles.append(profile)
    return profiles


def get_registry() -> list[ModelProfile]:
    """Cached accessor. Reloads if the configured path changes."""
    global _registry_cache
    path = settings.model_registry_path
    if _registry_cache is not None and _registry_cache[0] == Path(path):
        return _registry_cache[1]
    profiles = load_registry(path)
    _registry_cache = (Path(path), profiles)
    return profiles


# ---- legacy heuristic (extracted from providers.choose_ollama_model) ----

_NAME_TOKENS: dict[str, tuple[str, ...]] = {
    'coding': ('coder', 'code', 'devstral', 'starcoder'),
    'graph': ('gemma', 'qwen', 'nemotron', 'phi', 'llama'),
    'memory': ('gemma', 'qwen', 'nemotron', 'phi', 'llama'),
    'general': ('gemma', 'qwen', 'nemotron', 'phi', 'llama'),
}


def select_by_name_heuristic(task: str, models: list[dict[str, Any]]) -> str | None:
    """Pick the smallest model whose name matches a task-family token.

    Returns None when no installed model can be ranked (caller falls back to
    the configured default).
    """
    tokens = _NAME_TOKENS.get(task, _NAME_TOKENS['general'])
    candidates: list[tuple[int, int, str]] = []
    for item in models:
        name = str(item.get('name') or item.get('model') or '')
        size = int(item.get('size') or 0)
        rank = next(
            (index for index, token in enumerate(tokens) if token in name.lower()),
            len(tokens),
        )
        candidates.append((rank, size or 10**18, name))
    candidates = [item for item in candidates if item[2]]
    if candidates:
        candidates.sort()
        return candidates[0][2]
    return None


# ---- orchestration ----

def select_model(
    task: str,
    hardware_profile: str,
    installed_models: list[dict[str, Any]],
    requested: str | None,
    registry: list[ModelProfile],
) -> str:
    """Choose an Ollama model tag for a task.

    Order of preference:
      1. an explicit user `requested` model that is installed;
      2. a registry profile matching task_type + hardware_profile + installed;
      3. the name-heuristic over installed models;
      4. the configured default (settings.ollama_model).
    """
    installed_names = {str(m.get('name') or m.get('model') or '') for m in installed_models}

    if requested and requested in installed_names:
        return requested

    # Prefer verified profiles, then any matching profile, smallest first.
    matching = [
        p for p in registry
        if task in p.task_types
        and p.hardware_profile == hardware_profile
        and p.model in installed_names
    ]
    matching.sort(key=lambda p: (not p.verified, p.peak_ram_mb or 10**18))
    if matching:
        return matching[0].model

    heuristic = select_by_name_heuristic(task, installed_models)
    if heuristic:
        return heuristic

    return requested or settings.ollama_model
