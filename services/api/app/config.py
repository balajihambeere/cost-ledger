from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    redis_url: str

    bedrock_client_mode: str = "mock"
    aws_region: str = "ap-south-1"

    service_api_keys: str = ""  # "system:key,system:key"
    jwt_secret: str
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60

    admin_username: str = "admin"
    admin_password: str = "change-me-dev-only"

    api_host: str = "0.0.0.0"
    api_port: int = 8000
    log_level: str = "INFO"

    @property
    def service_api_key_map(self) -> dict[str, str]:
        pairs = [p for p in self.service_api_keys.split(",") if p.strip()]
        result: dict[str, str] = {}
        for pair in pairs:
            system, _, key = pair.partition(":")
            if system and key:
                result[key] = system
        return result


@lru_cache
def get_settings() -> Settings:
    return Settings()
