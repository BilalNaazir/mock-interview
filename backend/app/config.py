"""
config.py - Every setting the backend needs, in one place.

This file is the heart of the dev / staging / prod separation. The CODE is
identical in every environment; only these SETTINGS change. Each setting is
read from an environment variable (or from a .env file when running locally),
so the same Docker image can run as dev, staging or prod depending purely on
what values it's given.

Example: in dev, MONGODB_DB_NAME might be "mock_interview_dev", while in prod
it's "mock_interview_prod". The code never needs to know which one it is.
"""

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # pydantic-settings automatically matches each field to an environment
    # variable with the same name in capitals, e.g. `mongodb_uri` <- MONGODB_URI.
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Which environment is this? Used for logging and safety checks.
    # Literal means only these three values are allowed - a typo like "prd"
    # makes the app refuse to start, instead of silently misbehaving.
    environment: Literal["dev", "staging", "prod"] = "dev"

    # --- Database ---------------------------------------------------------
    mongodb_uri: str = "mongodb://localhost:27017"
    mongodb_db_name: str = "mock_interview_dev"

    # --- Login (AWS Cognito) ----------------------------------------------
    # Each environment has its OWN Cognito user pool, so test accounts in
    # staging can never log into production.
    cognito_region: str = "eu-north-1"
    cognito_user_pool_id: str = ""   # e.g. "eu-north-1_AbC123xyz"
    cognito_client_id: str = ""      # the app client ID from Cognito
    cognito_domain: str = ""         # e.g. "https://my-app-dev.auth.eu-north-1.amazoncognito.com"

    # --- Video storage (AWS S3) --------------------------------------------
    # Each environment has its OWN bucket, so dev recordings never mix with
    # real users' recordings in prod.
    aws_region: str = "eu-north-1"
    s3_videos_bucket: str = ""       # e.g. "mock-interview-dev-videos-bilal"

    # AWS access keys are NOT listed here on purpose. boto3 (the AWS library)
    # reads AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY from the environment
    # by itself. In dev they come from your .env file; on AWS (Phase 6) there
    # will be no keys at all - the container gets permissions from an IAM role.

    # --- Recording limits -----------------------------------------------------
    max_recording_seconds: int = 180       # 3 minutes per answer
    max_upload_mb: int = 100               # far more than 3 minutes needs
    upload_url_expiry_seconds: int = 600   # a presigned upload link works for 10 minutes
    video_url_expiry_seconds: int = 3600   # a playback link works for 1 hour

    # --- Browser access (CORS) ----------------------------------------------
    # Which website addresses may call this API. Comma-separated, because
    # environment variables are plain text. In dev this is the Vite server.
    cors_origins: str = "http://localhost:5173"

    # --- Values worked out from the settings above ---------------------------

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @property
    def cognito_issuer(self) -> str:
        """Who issues our login tokens. Every valid token must say this."""
        return f"https://cognito-idp.{self.cognito_region}.amazonaws.com/{self.cognito_user_pool_id}"

    @property
    def cognito_jwks_url(self) -> str:
        """Where Cognito publishes the public keys used to check token signatures."""
        return f"{self.cognito_issuer}/.well-known/jwks.json"


@lru_cache
def get_settings() -> Settings:
    """
    Load the settings once and reuse them. lru_cache remembers the result,
    so we don't re-read environment variables on every request.
    """
    return Settings()
