from __future__ import annotations

from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')

    app_name: str = 'InMyAI API'
    data_dir: Path = Path('./data/runtime')
    workspace_root: Path = Path('./workspace')
    allow_any_local_path: bool = False
    allowed_roots: str = ''
    max_file_mb: int = 2
    max_index_files: int = 5000
    provider: str = 'mock'
    ollama_base_url: str = 'http://127.0.0.1:11434'
    ollama_model: str = 'gemma3:4b'
    comfyui_base_url: str = 'http://127.0.0.1:8188'
    comfyui_workflow_path: str = ''
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
