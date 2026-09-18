from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "development"
    app_secret: str = "dev-secret-change-me"
    frontend_origin: str = "http://localhost:3000"
    database_url: str = "postgresql+psycopg://aitutor:aitutor@db:5432/aitutor"
    openai_api_key: str = ""
    openai_model: str = "gpt-5.6-terra"
    openai_reasoning_effort: str = "low"
    access_token_minutes: int = 60 * 24 * 7

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
