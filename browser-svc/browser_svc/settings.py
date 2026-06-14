"""Centralized settings for browser-svc."""

import functools
import os

from pydantic import BaseModel, Field


class BrowserSettings(BaseModel):
    """All env-var-driven configuration for browser-svc."""

    valkey_host: str = Field(default="valkey", alias="VALKEY_HOST")
    valkey_port: int = Field(default=6379, alias="VALKEY_PORT")


@functools.cache
def load_settings() -> BrowserSettings:
    return BrowserSettings.model_validate(dict(os.environ))
