from functools import lru_cache

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL


class DatabaseSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str | None = None
    postgres_host: str = "localhost"
    postgres_port: int = Field(default=5432, ge=1, le=65535)
    postgres_db: str = "credit"
    postgres_user: str = "credit"
    postgres_password: SecretStr | None = None

    @model_validator(mode="after")
    def configure_database(self):
        if not self.database_url:
            if self.postgres_password is None or not self.postgres_password.get_secret_value():
                raise ValueError("DATABASE_URL or POSTGRES_PASSWORD is required")
            self.database_url = URL.create(
                "postgresql+psycopg",
                username=self.postgres_user,
                password=self.postgres_password.get_secret_value(),
                host=self.postgres_host,
                port=self.postgres_port,
                database=self.postgres_db,
            ).render_as_string(hide_password=False)
        return self


class Settings(DatabaseSettings):
    jwt_secret: SecretStr = Field(min_length=32)
    ai_enabled: bool = False
    ai_service_token: SecretStr | None = None
    rabbitmq_url: SecretStr = SecretStr("amqp://guest:guest@localhost:5672/")
    token_minutes: int = Field(default=60, ge=1, le=1440)
    max_document_bytes: int = Field(default=10 * 1024 * 1024, ge=1, le=50 * 1024 * 1024)


@lru_cache
def get_settings() -> Settings:
    return Settings()
