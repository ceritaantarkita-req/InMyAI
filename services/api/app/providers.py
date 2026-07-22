from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import httpx

from .config import settings
from .model_registry import get_registry, select_by_name_heuristic


@dataclass
class ProviderResult:
    text: str
    model: str
    provider: str


class MockProvider:
    name = 'mock'

    async def chat(self, messages: list[dict[str, str]], model: str | None = None) -> ProviderResult:
        user = next((m['content'] for m in reversed(messages) if m['role'] == 'user'), '')
        context = next((m['content'] for m in messages if m['role'] == 'system'), '')
        context_excerpt = context[-3500:]
        text = (
            'I am running in deterministic demo mode, so I will not invent an answer from an unavailable model.\n\n'
            f'Your request: {user}\n\n'
            'Relevant local context retrieved by InMyAI:\n'
            f'{context_excerpt if context_excerpt.strip() else "No matching local context was found."}\n\n'
            'Next action: connect Ollama in Settings for a generative answer, or use the cited files and tools directly.'
        )
        return ProviderResult(text=text, model='deterministic-mock', provider='mock')


class OllamaProvider:
    name = 'ollama'

    async def chat(self, messages: list[dict[str, str]], model: str | None = None) -> ProviderResult:
        selected = model or settings.ollama_model
        payload = {'model': selected, 'messages': messages, 'stream': False, 'keep_alive': '5m'}
        async with httpx.AsyncClient(timeout=180) as client:
            response = await client.post(f'{settings.ollama_base_url}/api/chat', json=payload)
            response.raise_for_status()
            data = response.json()
        return ProviderResult(text=data['message']['content'], model=selected, provider='ollama')

    async def models(self) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.get(f'{settings.ollama_base_url}/api/tags')
            response.raise_for_status()
            return response.json().get('models', [])


    async def unload(self, model: str | None = None) -> None:
        selected = model or settings.ollama_model
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(
                f'{settings.ollama_base_url}/api/generate',
                json={'model': selected, 'keep_alive': 0}
            )
            response.raise_for_status()


def choose_ollama_model(task: str, models: list[dict[str, Any]], requested: str | None = None) -> str:
    """Select an installed Ollama model for a task.

    Prefers a verified/measured profile from the model registry
    (models/registry.json) that matches the task, the current hardware profile,
    and an installed model. Falls back to the name-heuristic, then the
    configured default.
    """
    import psutil

    names = [str(item.get('name') or item.get('model') or '') for item in models]
    if requested and requested in names:
        return requested

    total_gb = psutil.virtual_memory().total / (1024 ** 3)
    hardware_profile = 'lite' if total_gb < 12 else 'standard'
    registry = get_registry()

    from .model_registry import select_model
    return select_model(task, hardware_profile, models, requested, registry)


# Backwards-compat export: callers that imported the heuristic directly keep working.
_name_heuristic = select_by_name_heuristic


async def get_ollama_status() -> dict:
    try:
        provider = OllamaProvider()
        models = await provider.models()
        return {'available': True, 'models': models, 'base_url': settings.ollama_base_url}
    except Exception as exc:
        return {'available': False, 'models': [], 'base_url': settings.ollama_base_url, 'error': str(exc)}
