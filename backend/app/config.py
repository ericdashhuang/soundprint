from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    spotify_client_id: str
    spotify_client_secret: str
    database_url: str = "postgresql+psycopg://soundprint:soundprint@localhost:5432/soundprint"
    cors_origins: str = "http://localhost:3000"
    # Eagerly warms the Spotify/ReccoBeats connections at process startup (see
    # app/warmup.py). Tests disable this via conftest.py so the suite never
    # makes a real outbound HTTP call.
    warm_up_on_startup: bool = True

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
