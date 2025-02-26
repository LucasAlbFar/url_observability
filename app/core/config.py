"""Application settings."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Class that contains application settings as attributes."""

    APP_NAME: str = "FastAPI Throughput API's Project"
    DEBUG: bool = True

    model_config = {"env_file": ".env"}


settings = Settings()
