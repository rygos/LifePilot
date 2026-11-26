from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    secret_key: str = "development-only-change-me"
    login_global_per_minute: int = Field(default=300, ge=10, le=5000)
    login_peer_per_minute: int = Field(default=60, ge=5, le=5000)
    login_account_per_10_minutes: int = Field(default=10, ge=3, le=100)
    database_url: str = "sqlite:///./lifepilot.db"
    redis_url: str = ""
    life_pilot_bootstrap_username: str = "admin"
    life_pilot_bootstrap_password: str = "change-this-password"
    mcp_api_key: str = ""
    mcp_port: int = 8002
    portainer_webhook_url: str = ""
    portainer_api_url: str = ""
    portainer_api_key: str = ""
    portainer_endpoint_id: int = Field(default=0, ge=0)
    portainer_stack_name: str = "lifepilot"
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
    transcription_base_url: str = ""
    transcription_api_key: str = ""
    transcription_model: str = "whisper-1"
    transcription_timeout_seconds: int = Field(default=90, ge=1, le=180)
    push_vapid_private_key: str = ""
    push_vapid_subject: str = ""
    imap_host: str = ""
    imap_port: int = Field(default=993, ge=1, le=65535)
    trash_retention_days: int = Field(default=30, ge=1, le=365)
    data_dir: str = "/app/data"

settings = Settings()
