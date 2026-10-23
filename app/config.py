from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Application Settings
    app_name: str = "MarketLens"
    environment: str = "development"
    port: int = 8000
    database_url: str = "sqlite+aiosqlite:///./marketlens.db"

    # Groq AI Configuration (No hardcoded models - driven by .env)
    groq_api_key: Optional[str] = None
    groq_model: str = "llama-3.3-70b-versatile"
    groq_temperature: float = 0.2

    # SEO Search Volume Configuration
    seo_provider: str = "mock"  # dataforseo_sandbox, rapidapi, mock
    seo_api_key: Optional[str] = None
    seo_api_login: Optional[str] = None

    # Notification Settings
    slack_webhook_url: Optional[str] = None
    email_provider: str = "resend"  # resend or smtp
    resend_api_key: Optional[str] = None
    notification_email_to: Optional[str] = "alerts@example.com"

    # SMTP Settings (if email_provider == "smtp")
    smtp_host: Optional[str] = None
    smtp_port: int = 587
    smtp_user: Optional[str] = None
    smtp_password: Optional[str] = None
    smtp_from: str = "alerts@marketlens.io"


settings = Settings()
