from pydantic import BaseSettings

class Settings(BaseSettings):
    APP_NAME: str = "FastAPI Throughput API's Project"
    DEBUG: bool = True

    class Config:
        env_file = ".env"

settings = Settings()
