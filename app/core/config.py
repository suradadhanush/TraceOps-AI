from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://eas_user:eas_pass@localhost:5432/eas_db"
    SYNC_DATABASE_URL: str = "postgresql://eas_user:eas_pass@localhost:5432/eas_db"

    # Redis / Celery
    REDIS_URL: str = "redis://localhost:6379/0"
    CELERY_BROKER_URL: str = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/1"

    # AI Providers
    OPENAI_API_KEY: str = ""
    ANTHROPIC_API_KEY: str = ""

    # LLM Analyzer
    LLM_PROVIDER: str = "openai"  # "openai" | "anthropic"
    LLM_MODEL: str = "gpt-4o"

    # Loop Detection
    EMBEDDING_SIMILARITY_THRESHOLD: float = 0.85
    LOOP_MIN_OCCURRENCES: int = 3

    # Scoring velocity thresholds (hours)
    VELOCITY_FAST_THRESHOLD_HOURS: int = 3
    VELOCITY_MED_THRESHOLD_HOURS: int = 6

    # App
    APP_ENV: str = "development"
    SECRET_KEY: str = "change-me-in-production"
    LOG_LEVEL: str = "INFO"


settings = Settings()
