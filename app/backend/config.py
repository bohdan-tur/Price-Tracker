from pydantic_settings import BaseSettings,SettingsConfigDict



class Settings(BaseSettings):
    DATABASE_URL: str
    ACCESS_TOKEN_SECRET_KEY: str
    REFRESH_TOKEN_SECRET_KEY: str
    ALGORITHM: str
    ACCESS_TOKEN_EXPIRES_MINUTES: int
    REFRESH_TOKEN_EXPIRES_DAYS: int


    model_config = SettingsConfigDict(env_file =".env",
                                      env_file_encoding="utf-8",
                                      extra="ignore"
    )





settings = Settings()