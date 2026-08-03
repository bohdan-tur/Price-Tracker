from enum import StrEnum
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(StrEnum):
    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"


MIN_SECRET_KEY_BYTES = 32


class Settings(BaseSettings):
    ENVIRONMENT: Environment

    DATABASE_URL: str
    TEST_DATABASE_URL: str | None = None

    ACCESS_TOKEN_SECRET_KEY: str
    REFRESH_TOKEN_SECRET_KEY: str
    ALGORITHM: Literal["HS256"] = "HS256"
    ACCESS_TOKEN_EXPIRES_MINUTES: int = Field(default=20, gt=0)
    REFRESH_TOKEN_EXPIRES_DAYS: int = Field(default=14, gt=0)

    DEBUG: bool = False

    SEED_DEFAULT_USERS: bool = False
    SEED_ADMIN_PASSWORD: str | None = None
    SEED_USER_PASSWORD: str | None = None

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        env_ignore_empty=True,
    )

    @model_validator(mode="after")
    def validate_security_settings(self) -> "Settings":
        secrets = {
            "ACCESS_TOKEN_SECRET_KEY": self.ACCESS_TOKEN_SECRET_KEY,
            "REFRESH_TOKEN_SECRET_KEY": self.REFRESH_TOKEN_SECRET_KEY,
        }

        for name, value in secrets.items():
            if len(value.encode("utf-8")) < MIN_SECRET_KEY_BYTES:
                raise ValueError(
                    f"{name} must contain at least {MIN_SECRET_KEY_BYTES} bytes"
                )

        if self.ACCESS_TOKEN_SECRET_KEY == self.REFRESH_TOKEN_SECRET_KEY:
            raise ValueError("Access and refresh token secrets must be different")

        if self.ENVIRONMENT is Environment.TEST and not self.TEST_DATABASE_URL:
            raise ValueError("TEST_DATABASE_URL is required in the test environment")

        if self.SEED_DEFAULT_USERS and (
            not self.SEED_ADMIN_PASSWORD or not self.SEED_USER_PASSWORD
        ):
            raise ValueError(
                "Seed passwords are required when SEED_DEFAULT_USERS is enabled"
            )

        if self.ENVIRONMENT is Environment.PRODUCTION:
            if self.DEBUG:
                raise ValueError("DEBUG must be false in production")
            if self.SEED_DEFAULT_USERS:
                raise ValueError("Default users cannot be seeded in production")

        return self


settings = Settings()
