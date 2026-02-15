from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # App
    app_env: str = "development"
    app_debug: bool = True

    # Database
    database_url: str = "sqlite+aiosqlite:///./videomuse.db"

    # LLM
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str = ""
    llm_model: str = "gpt-4o-mini"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Bilibili
    bilibili_sessdata: str = ""


settings = Settings()
