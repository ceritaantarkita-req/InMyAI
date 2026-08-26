from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, Field, model_validator


class ProjectCreate(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    path: str = Field(min_length=1)


class AllowedRootCreate(BaseModel):
    path: str = Field(min_length=1)


class ChatRequest(BaseModel):
    project_id: int
    message: str = Field(min_length=1, max_length=20_000)
    conversation_id: int | None = None
    provider: Literal['auto', 'mock', 'ollama', 'openrouter'] = 'auto'
    model: str | None = Field(default=None, max_length=192)
    connection_id: str | None = Field(default=None, pattern=r'^conn_[A-Za-z0-9_-]{16,96}$')
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=256, pattern=r'^[A-Za-z0-9][A-Za-z0-9._:/-]{7,255}$')
    input_sensitivity: Literal['PUBLIC', 'INTERNAL'] = 'INTERNAL'
    requested_output_tokens: int = Field(default=1024, ge=1, le=8192)


class MemoryCreate(BaseModel):
    project_id: int
    kind: Literal['working', 'episodic', 'semantic', 'procedural', 'artifact']
    title: str = Field(min_length=2, max_length=200)
    content: str = Field(min_length=1, max_length=100_000)
    source: str = 'user'
    confidence: float = Field(default=1.0, ge=0, le=1)


class DecisionCreate(BaseModel):
    project_id: int
    statement: str = Field(min_length=3, max_length=20_000)
    rationale: str = Field(default='', max_length=20_000)
    supersedes_id: int | None = None
    source: str = 'user'
    approved_by: str = 'user'


class WriteProposalCreate(BaseModel):
    project_id: int
    relative_path: str = Field(min_length=1, max_length=1000)
    proposed_content: str = Field(max_length=2_000_000)


class SearchRequest(BaseModel):
    project_id: int
    query: str = Field(min_length=1, max_length=1000)
    limit: int = Field(default=8, ge=1, le=50)


class OCRRequest(BaseModel):
    project_id: int
    relative_path: str
    language: str = 'eng'


class ImageRequest(BaseModel):
    project_id: int
    prompt: str = Field(min_length=3, max_length=5000)
    negative_prompt: str = Field(default='', max_length=5000)
    width: int = Field(default=512, ge=256, le=1024)
    height: int = Field(default=512, ge=256, le=1024)
    steps: int = Field(default=4, ge=1, le=30)
    seed: int = -1
    provider: Literal['simulator', 'comfyui', 'diffusers'] = 'simulator'


class AgentCreate(BaseModel):
    project_id: int
    slug: str = Field(pattern=r'^[a-z0-9-]+$', min_length=2, max_length=60)
    name: str = Field(min_length=2, max_length=100)
    role: str = Field(min_length=3, max_length=500)
    provider: str = 'auto'
    model: str = 'auto'
    tools: list[str] = Field(default_factory=lambda: ['search_project', 'read_file'])


class TaskCreate(BaseModel):
    project_id: int
    title: str = Field(min_length=2, max_length=200)
    instruction: str = Field(min_length=3, max_length=20_000)
    provider: str = 'auto'


class SandboxRunInput(BaseModel):
    # Mirrors InMySandbox's own lib/policy.mjs validateInputs(): flat
    # filename only (no '/', no subdirectories), content is text.
    path: str = Field(min_length=1, max_length=120, pattern=r'^[A-Za-z0-9._-]{1,120}$')
    content: str = Field(default='', max_length=131_072)


class SandboxRunRequest(BaseModel):
    # Q11.1 Piece 3b: explicit, user-initiated small-script execution in a
    # real isolated InMySandbox R1 sandbox. Deliberately NOT for running a
    # project's actual test suite -- see connect_inmysandbox.py and this
    # piece's design doc for why InMySandbox v0.1's real constraints
    # (network=none, inputs capped at 20 flat files / 128 KiB combined,
    # bare runtime images) cannot fit that. Field bounds below mirror
    # InMySandbox's own lib/policy.mjs validatePolicy()/validateCommand()
    # ranges so an out-of-range request fails fast here rather than only
    # after a Hub authorization round-trip.
    command: list[str] = Field(min_length=1, max_length=32)
    inputs: list[SandboxRunInput] = Field(default_factory=list, max_length=20)
    image: str = Field(default='python:3.13-alpine', min_length=1, max_length=128)
    timeout_ms: int = Field(default=60_000, ge=1_000, le=300_000)
    memory_mb: int = Field(default=512, ge=64, le=8192)
    cpus: float = Field(default=1.0, ge=0.1, le=4)
    pids: int = Field(default=128, ge=16, le=512)
    disk_mb: int = Field(default=256, ge=32, le=4096)
    ttl_seconds: int = Field(default=900, ge=30, le=3600)
    idempotency_key: str = Field(min_length=8, max_length=256, pattern=r'^[A-Za-z0-9][A-Za-z0-9._:/-]{7,255}$')
    input_sensitivity: Literal['PUBLIC', 'INTERNAL'] = 'INTERNAL'

    @model_validator(mode='after')
    def _check_combined_input_bytes(self) -> 'SandboxRunRequest':
        total = sum(len(item.content.encode('utf-8')) for item in self.inputs)
        if total > 131_072:
            raise ValueError('Combined inputs content exceeds 128 KiB, the InMySandbox v0.1 policy cap.')
        return self
