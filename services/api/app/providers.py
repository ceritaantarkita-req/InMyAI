from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import httpx

from .config import settings


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
    names = [str(item.get('name') or item.get('model') or '') for item in models]
    if requested and requested in names:
        return requested
    preferences = {
        'coding': ('coder', 'code', 'devstral', 'starcoder'),
        'graph': ('gemma', 'qwen', 'nemotron', 'phi', 'llama'),
        'memory': ('gemma', 'qwen', 'nemotron', 'phi', 'llama'),
        'general': ('gemma', 'qwen', 'nemotron', 'phi', 'llama')
    }
    tokens = preferences.get(task, preferences['general'])
    candidates = []
    for item in models:
        name = str(item.get('name') or item.get('model') or '')
        size = int(item.get('size') or 0)
        rank = next((index for index, token in enumerate(tokens) if token in name.lower()), len(tokens))
        candidates.append((rank, size or 10**18, name))
    candidates = [item for item in candidates if item[2]]
    if candidates:
        candidates.sort()
        return candidates[0][2]
    return requested or settings.ollama_model


async def get_ollama_status() -> dict:
    try:
        provider = OllamaProvider()
        models = await provider.models()
        return {'available': True, 'models': models, 'base_url': settings.ollama_base_url}
    except Exception as exc:
        return {'available': False, 'models': [], 'base_url': settings.ollama_base_url, 'error': str(exc)}
