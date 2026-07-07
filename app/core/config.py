"""
Application configuration loaded from environment variables (.env).
Centralizing settings here keeps secrets out of source code.
"""
from functools import lru_cache
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Database
    DATABASE_URL: str 
    ONLINE_DATABASE_URL: str

    # Security
    SECRET_KEY: str 
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # Notifications
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USERNAME: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM_EMAIL: str = "no-reply@saccosystem.example"

    AFRICAS_TALKING_USERNAME: str = "sandbox"
    AFRICAS_TALKING_API_KEY: str = ""

    FCM_SERVER_KEY: str = ""

        # Mobile Money (MarzPay)
    MARZPAY_API_KEY: str = ""
    MARZPAY_API_SECRET: str = ""
    MARZPAY_BASE_URL: str = "https://wallet.wearemarz.com/api/v1"
    PUBLIC_BASE_URL: str = "http://localhost:8000"

        # SMS (MarzSMS - https://sms.wearemarz.com/docs)
    MARZSMS_API_KEY: str = ""
    MARZSMS_API_SECRET: str = ""
    MARZSMS_BASE_URL: str = "https://sms.wearemarz.com/api/v1"
    MARZSMS_SENDER_ID: str = ""



    # Used in SMS message templates, e.g. "- Kampala SACCO"
    SACCO_NAME: str



    # App
    ENVIRONMENT: str = "development"
    DORMANCY_THRESHOLD_MONTHS: int = 6
    CORS_ORIGINS: str

    @property
    def cors_origins_list(self) -> List[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

@lru_cache
def get_settings() -> Settings:
    return Settings() # pyright: ignore[reportCallIssue]


settings = get_settings()
