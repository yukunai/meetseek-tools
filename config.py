from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    database_url: str
    jwt_secret_key: SecretStr
    password_hash_salt: SecretStr

    cors_allowed_origins: str = ""
    site_url: str = "https://meetseek.ai"
    max_upload_bytes: int = 8 * 1024 * 1024
    max_json_body_bytes: int = 2 * 1024 * 1024
    max_image_side: int = 1920
    webp_quality: int = 82
    login_failure_delay_seconds: float = 1.5
    admin_failure_delay_seconds: float = 1.0
    auth_cookie_name: str = "meetseek_session"
    auth_cookie_domain: str | None = None
    auth_cookie_max_age: int = 60 * 60 * 24 * 30
    parse_url_timeout_seconds: float = 3.0

    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_timeout: int = 30
    db_pool_recycle: int = 1800

    mock_user_id: int = 1
    mock_reputation: int = 30
    mock_is_admin: bool = False
    mock_login_password: SecretStr | None = None

    @property
    def allowed_cors_origins(self) -> list[str]:
        origins = [origin.strip().rstrip("/") for origin in self.cors_allowed_origins.split(",") if origin.strip()]
        if "*" in origins:
            raise ValueError("CORS_ALLOWED_ORIGINS must not contain '*'")
        return origins


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
