from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration loaded from environment variables.

    All values come from the environment (or a local .env file in dev) so the
    same image runs unchanged across dev/staging/prod — only the injected env
    differs.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Full DSN wins if provided; otherwise assembled from the parts below.
    database_url: str | None = None

    postgres_host: str = "db"
    postgres_port: int = 5432
    postgres_db: str = "serviot"
    postgres_user: str = "serviot"
    postgres_password: str = "serviot"

    # Connection pool bounds. Keep small — the app is I/O light and we do not
    # want to exhaust Postgres' max_connections behind a few app replicas.
    db_pool_min: int = 1
    db_pool_max: int = 10

    app_name: str = "serviot-devices-api"
    app_env: str = "development"

    @property
    def dsn(self) -> str:
        if self.database_url:
            return self.database_url
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
