from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, Field


class ProjectCreate(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    path: str = Field(min_length=1)


class ChatRequest(BaseModel):
    project_id: int
    message: str = Field(min_length=1, max_length=20_000)
    conversation_id: int | None = None
    provider: Literal['auto', 'mock', 'ollama'] = 'auto'
    model: str | None = None


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
