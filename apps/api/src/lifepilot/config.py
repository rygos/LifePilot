from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    secret_key: str = "development-only-change-me"
    database_url: str = "sqlite:///./lifepilot.db"
    redis_url: str = ""
    life_pilot_bootstrap_username: str = "admin"
    life_pilot_bootstrap_password: str = "change-this-password"
    mcp_api_key: str = ""
    mcp_port: int = 8002
    web_origin: str = "http://localhost:3000"

settings = Settings()
