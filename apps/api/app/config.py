from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: Literal["development", "test", "staging", "production"] = "development"
    database_url: str = "postgresql+psycopg://damdam:damdam@localhost:5432/damdam"
    redis_url: str = "redis://localhost:6379/0"
    jwt_secret: str = Field(
        default="development-only-secret-change-before-deploy",
        min_length=32,
    )
    jwt_access_ttl_minutes: int = 15
    jwt_refresh_ttl_days: int = 30

    otp_provider_primary: Literal["termii", "twilio"] = "termii"
    otp_provider_secondary: Literal["termii", "twilio"] = "twilio"
    otp_failover_threshold_seconds: int = 180
    otp_request_timeout_seconds: int = 10
    otp_ttl_seconds: int = 600
    otp_attempt_limit: int = 3
    otp_lockout_seconds: int = 60
    otp_resend_cooldown_seconds: int = 30
    otp_requests_per_hour: int = 3

    termii_base_url: str = "https://api.ng.termii.com"
    termii_api_key: str = ""
    termii_sender_id: str = "DamDam"
    termii_webhook_secret: str = ""
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_verify_service_sid: str = ""

    @model_validator(mode="after")
    def providers_must_differ(self) -> "Settings":
        if self.otp_provider_primary == self.otp_provider_secondary:
            raise ValueError("OTP primary and secondary providers must differ")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
