from __future__ import annotations

from pathlib import Path
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # env_prefix='INMYAI_' matches .env.example and the README (INMYAI_PROVIDER,
    # INMYAI_ALLOWED_ROOTS, INMYAI_DATA_DIR, etc.). Without this, pydantic-settings
    # only ever bound the bare, unprefixed names (PROVIDER, ALLOWED_ROOTS, ...),
    # so every documented INMYAI_* override silently had no effect. Ollama/ComfyUI
    # fields keep their bare validation_alias below because .env.example and the
    # README intentionally document them unprefixed (OLLAMA_BASE_URL, OLLAMA_MODEL,
    # COMFYUI_BASE_URL, COMFYUI_WORKFLOW_PATH) so they line up with the env vars
    # those tools' own docs use. An explicit validation_alias is read verbatim and
    # is not affected by env_prefix.
    model_config = SettingsConfigDict(env_file='.env', env_prefix='INMYAI_', extra='ignore')

    app_name: str = 'InMyAI API'
    data_dir: Path = Path('./data/runtime')
    workspace_root: Path = Path('./workspace')
    allow_any_local_path: bool = False
    allowed_roots: str = ''
    max_file_mb: int = 8
    max_index_files: int = 5000
    provider: str = 'mock'
    ollama_base_url: str = Field('http://127.0.0.1:11434', validation_alias='OLLAMA_BASE_URL')
    ollama_model: str = Field('gemma3:4b', validation_alias='OLLAMA_MODEL')
    comfyui_base_url: str = Field('http://127.0.0.1:8188', validation_alias='COMFYUI_BASE_URL')
    comfyui_workflow_path: str = Field('', validation_alias='COMFYUI_WORKFLOW_PATH')
    diffusers_model_id: str = 'stabilityai/sd-turbo'
    model_registry_path: Path = Path('models/registry.json')
    idle_model_timeout_seconds: int = 300

    @property
    def database_path(self) -> Path:
        return self.data_dir / 'inmyai.sqlite'

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.workspace_root.mkdir(parents=True, exist_ok=True)


settings = Settings()
settings.ensure_dirs()
