"""Centralized settings for agent-svc."""

import functools
import os

from pydantic import BaseModel, Field


class AgentSettings(BaseModel):
    """All env-var-driven configuration for agent-svc."""

    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    valkey_host: str = Field(default="valkey", alias="VALKEY_HOST")
    valkey_port: int = Field(default=6379, alias="VALKEY_PORT")
    valkey_db: int = Field(default=0, alias="VALKEY_DB")
    scraper_url: str = Field(default="http//scraper-svc:8001", alias="SCRAPER_URL")
    searxng_url: str = Field(default="http//searxng:8080", alias="SEARXNG_URL")
    semantic_url: str = Field(default="http//semantic-svc:8003", alias="SEMANTIC_URL")
    llm_base_url: str = Field(default="http//llm-svc:8011/v1", alias="LLM_BASE_URL")
    llm_api_key: str = Field(default="", alias="LLM_API_KEY")
    llm_model: str = Field(default="deepseek-v4-flash", alias="LLM_MODEL")
    llm_enable_thinking: bool = Field(default=False, alias="LLM_ENABLE_THINKING")
    api_key: str = Field(default="", alias="API_KEY")
    webhook_secret: str = Field(default="", alias="WEBHOOK_SECRET")


@functools.cache
def load_settings() -> AgentSettings:
    return AgentSettings.model_validate(dict(os.environ))
