from __future__ import annotations

from dataclasses import asdict, dataclass
import psutil


@dataclass
class RouteDecision:
    task: str
    engine: str
    provider: str
    reason: str
    estimated_ram_mb: int
    context_limit: int


def classify_task(message: str) -> str:
    text = message.lower()
    if any(token in text for token in ('ocr', 'scan', 'invoice', 'extract text', 'baca gambar')):
        return 'ocr'
    if any(token in text for token in ('generate image', 'buat gambar', 'image generation', 'ilustrasi')):
        return 'image'
    if any(token in text for token in ('diff', 'bandingkan file', 'compare file')):
        return 'diff'
    if any(token in text for token in ('import', 'function', 'class', 'dependency', 'hubungan', 'graph')):
        return 'graph'
    if any(token in text for token in ('error', 'bug', 'typescript', 'code', 'coding', 'refactor', 'test')):
        return 'coding'
    if any(token in text for token in ('keputusan', 'decision', 'terakhir', 'memory', 'ingat')):
        return 'memory'
    return 'general'


def route(message: str, requested_provider: str, ollama_available: bool) -> RouteDecision:
    task = classify_task(message)
    available_gb = psutil.virtual_memory().available / (1024 ** 3)
    context_limit = 4096 if available_gb < 5 else 8192

    deterministic_only = {
        'ocr': ('tesseract', 'local-tool', 'OCR is more accurate and efficient with a dedicated engine.', 350),
        'diff': ('diff', 'local-tool', 'A deterministic diff is safer than asking an LLM to compare raw files.', 50),
        'image': ('image-router', 'local-tool', 'Image requests use a dedicated image backend and unload chat models.', 900)
    }
    if task in deterministic_only:
        engine, provider, reason, ram = deterministic_only[task]
        return RouteDecision(task, engine, provider, reason, ram, context_limit)

    augmented = {
        'graph': ('graph+small-llm', 'AST and graph traversal retrieve evidence before explanation.'),
        'memory': ('memory+small-llm', 'The decision ledger and memory store retrieve active context before explanation.')
    }
    if task in augmented:
        engine, reason = augmented[task]
        provider = 'ollama' if ollama_available and requested_provider != 'mock' else 'mock'
        return RouteDecision(task, engine, provider, reason, 3400 if provider == 'ollama' else 150, context_limit)

    if requested_provider == 'mock':
        return RouteDecision(task, 'small-llm', 'mock', 'Mock mode was explicitly selected.', 100, context_limit)
    if requested_provider == 'ollama' and ollama_available:
        return RouteDecision(task, 'small-llm', 'ollama', 'Ollama was explicitly selected and is available.', 3400, context_limit)
    if requested_provider == 'ollama' and not ollama_available:
        return RouteDecision(task, 'small-llm', 'mock', 'Ollama is unavailable; safe deterministic fallback selected.', 100, context_limit)
    if ollama_available:
        return RouteDecision(task, 'small-llm', 'ollama', 'A generative task was detected and local Ollama is available.', 3400, context_limit)
    return RouteDecision(task, 'small-llm', 'mock', 'No local model runtime is available; safe fallback selected.', 100, context_limit)


def to_dict(decision: RouteDecision) -> dict:
    return asdict(decision)
