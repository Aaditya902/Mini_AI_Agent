from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # LLM
    gemini_api_key: str = ""
    model: str = "gemini-2.5-flash"
    max_tokens: int = 1024
    temperature: float = 0.3
    llm_timeout_seconds: int = 30

    # Agent
    max_tool_iterations: int = 5
    enable_stub: bool = False          # set to true to skip real LLM calls

    # Service
    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "info"


settings = Settings()
