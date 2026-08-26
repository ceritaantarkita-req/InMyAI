from __future__ import annotations

from pathlib import Path
from pydantic import Field, SecretStr
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

    # Phase 5 governed cloud-provider bridge. This is the local InMyConnect
    # HTTP boundary, never the provider API origin. The service credential is
    # the InMyHub identity credential for agent:inmyai; it is server-side only
    # and must never be returned to the browser or used as an OpenRouter key.
    connect_base_url: str = 'http://127.0.0.1:8766'
    connect_timeout_seconds: float = 20.0
    hub_service_token: SecretStr = SecretStr('')

    # Q11.1 (Phase 10, 2026-08-25): InMySandbox R1 execution (see
    # connect_inmysandbox.py). Unlike OpenRouter, this has no bridge process
    # of its own -- InMyAI talks to InMyHub's authority routes directly
    # (reusing hub_service_token above, the same agent:inmyai credential
    # already used for InMyConnect) and to InMySandbox's own loopback API
    # directly. Defaults match each product's own real default port
    # (InMyHub: server/config.mjs parsePort() default 8787; InMySandbox:
    # server.mjs's INMYSANDBOX_PORT default 17421).
    hub_base_url: str = 'http://127.0.0.1:8787'
    hub_authority_timeout_seconds: float = 20.0
    inmysandbox_base_url: str = 'http://127.0.0.1:17421'
    inmysandbox_timeout_seconds: float = 305.0

    @property
    def database_path(self) -> Path:
        return self.data_dir / 'inmyai.sqlite'

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.workspace_root.mkdir(parents=True, exist_ok=True)


settings = Settings()
settings.ensure_dirs()
