import json
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql://trading_user:trading_pass@localhost:5432/trading_research"
    secret_key: str = "change-me-in-production-use-a-long-random-string"
    algorithm: str = "HS256"
    access_token_expire_hours: int = 24

    anthropic_api_key: str = ""
    polygon_api_key: str = ""
    email_sender: str = ""
    email_app_password: str = ""
    sendgrid_api_key: str = ""

    # Accept JSON array, comma-separated string, or "*" from environment.
    # Example: CORS_ORIGINS=https://yourapp.vercel.app,https://www.yourapp.com
    cors_origins_raw: str = ""

    @property
    def cors_origins(self) -> list[str]:
        raw = self.cors_origins_raw.strip()
        if not raw:
            return ["http://localhost:5173", "http://localhost:3000", "http://localhost:80"]
        if raw == "*":
            return ["*"]
        if raw.startswith("["):
            return json.loads(raw)
        return [o.strip() for o in raw.split(",") if o.strip()]

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
        env_prefix="",
        populate_by_name=True,
    )


settings = Settings()
