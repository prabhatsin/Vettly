from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_FILE = Path(__file__).resolve().parents[2] / ".env"
# config.py is at api/app/config.py, so parents[2] is the repo root. This finds your root .env no matter
#  which folder you run uvicorn from.

class Settings(BaseSettings):
    database_url: str
    redis_url: str
    
    cors_origins: list[str] = ["http://localhost:3000"]

    model_config = SettingsConfigDict(env_file=ENV_FILE, extra="ignore")
    # extra="ignore": your .env also holds POSTGRES_USER, POSTGRES_PASSWORD and POSTGRES_DB, which this 
    # class doesn’t declare. Without this line, pydantic raises an “extra inputs not permitted” error.
settings = Settings()