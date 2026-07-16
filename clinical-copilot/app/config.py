"""Runtime configuration. All secrets come from the environment — never committed (fixes AUDIT A2)."""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="COPILOT_", env_file=".env", extra="ignore")

    # --- OpenEMR database (read-only bounded reads; see AUDIT §3 fast path) ---
    db_host: str = "127.0.0.1"
    db_port: int = 8320
    db_user: str = "openemr"
    db_password: str = "openemr"
    db_name: str = "openemr"
    db_pool_min: int = 1
    db_pool_max: int = 10

    # --- LLM provider (BAA-covered per case study; demo data only) ---
    llm_provider: str = "openai"          # openai | mock
    llm_api_key: str = ""
    llm_base_url: str | None = None
    llm_model_fast: str = "gpt-4o-mini"
    llm_model_synth: str = "gpt-4o"
    llm_timeout_s: float = 30.0

    # --- Observability (Langfuse) ---
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "https://cloud.langfuse.com"
    # Mark traces publicly shareable (demo deployment only — data is synthetic Synthea,
    # so graders can inspect traces without a Langfuse login). Never enable with real PHI.
    langfuse_public_traces: bool = False
    langfuse_project_id: str = ""  # used to build shareable trace URLs in responses

    # --- Behaviour ---
    brief_tool_timeout_s: float = 8.0
    max_labs: int = 100
    max_encounters: int = 25
    environment: str = "dev"

    # --- Week 2 multimodal ---
    w2_enabled: bool = True
    w2_rerank_enabled: bool = False  # Cohere rerank hook — hybrid score stand-in when false

    @property
    def llm_enabled(self) -> bool:
        return self.llm_provider != "mock" and bool(self.llm_api_key)

    @property
    def langfuse_enabled(self) -> bool:
        return bool(self.langfuse_public_key and self.langfuse_secret_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
