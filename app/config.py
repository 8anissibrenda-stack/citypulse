"""CityPulse application configuration via environment variables."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment / .env file."""

    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "INFO"
    db_path: str = "data/citypulse.db"
    pipeline_mode: str = "simulator"
    active_camera_id: int = 1

    model_config = {
        "env_prefix": "CITYPULSE_",
        "env_file": ".env",
        "env_file_encoding": "utf-8",
    }


settings = Settings()
