import os
import json
from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # App
    app_name: str = "product-copilot"
    environment: str = "dev"
    log_level: str = "INFO"
    host: str = "0.0.0.0"
    port: int = 8080

    # AWS
    aws_region: str = "us-east-1"

    # CodeMax (OpenAI-compatible LLM)
    codermax_api_key: str = ""
    codermax_base_url: str = "https://api.codemax.pro"
    codermax_model: str = "claude-sonnet-4-6"

    # Qdrant Cloud
    qdrant_url: str = ""
    qdrant_api_key: str = ""

    # RDS
    db_host: str = ""
    db_port: int = 5432
    db_name: str = "productcopilot"
    db_user: str = "copilot_user"
    db_password: str = ""

    # Redis
    redis_host: str = ""
    redis_port: int = 6379
    redis_password: str = ""
    redis_use_ssl: bool = True

    # Slack
    slack_bot_token: str = ""
    slack_signing_secret: str = ""
    slack_app_token: str = ""

    # Jira
    jira_url: str = ""
    jira_email: str = ""
    jira_api_token: str = ""
    jira_project_key: str = ""

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


@lru_cache
def get_settings() -> Settings:
    return Settings()
