from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    secret_key: str = "development-only-change-me"
    database_url: str = "sqlite:///./lifepilot.db"
    redis_url: str = ""
    life_pilot_bootstrap_username: str = "admin"
    life_pilot_bootstrap_password: str = "change-this-password"
    mcp_api_key: str = ""
    mcp_port: int = 8002
    portainer_webhook_url: str = ""
    life_pilot_commit_sha: str = ""
    web_origin: str = "http://localhost:3000"
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = ""
    llm_timeout_seconds: int = Field(default=15, ge=1, le=120)
    embedding_base_url: str = ""
    embedding_api_key: str = ""
    embedding_model: str = ""
    embedding_timeout_seconds: int = Field(default=15, ge=1, le=120)
    data_dir: str = "/app/data"

settings = Settings()
