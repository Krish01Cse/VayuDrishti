"""
config.py — VayuDrishti (DustWatch) backend configuration.

All runtime settings are read from environment variables.
Set USE_LOCALSTACK=true (or 1 / yes) to point every AWS client
at the local LocalStack endpoint instead of real AWS.

Vision provider is controlled by VISION_PROVIDER:
  "bedrock"  → AWS Bedrock / Claude Haiku
  "openai"   → OpenAI Vision API
  "mock"     → hard-coded valid response (safe default for dev)
"""

from __future__ import annotations

import ast
import json
import os
from functools import lru_cache
from typing import Any, Literal, Optional

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _bool_env(key: str, default: bool = False) -> bool:
    """Parse a boolean-ish environment variable."""
    val = os.getenv(key, str(default)).strip().lower()
    return val in {"1", "true", "yes", "on"}


# ---------------------------------------------------------------------------
# Settings model
# ---------------------------------------------------------------------------

class Settings(BaseSettings):
    """
    Application-wide settings, loaded from environment variables.
    All fields have sensible defaults so the app starts without any env setup.
    """

    # ------------------------------------------------------------------
    # General
    # ------------------------------------------------------------------
    APP_NAME: str = "VayuDrishti"
    APP_VERSION: str = "0.1.0"
    DEBUG: bool = Field(default=False)
    LOG_LEVEL: str = Field(default="INFO")

    # ------------------------------------------------------------------
    # LocalStack toggle
    # Set USE_LOCALSTACK=true to use a local AWS-compatible endpoint.
    # ------------------------------------------------------------------
    USE_LOCALSTACK: bool = Field(default=False)
    LOCALSTACK_ENDPOINT: str = Field(default="http://localhost:4566")

    # ------------------------------------------------------------------
    # AWS credentials / region
    # When deployed on AWS (App Runner, ECS, Lambda, EC2), leave keys empty
    # so boto3 automatically uses the IAM execution role / instance profile.
    # For LocalStack, dummy values ("test") will be used automatically.
    # ------------------------------------------------------------------
    AWS_REGION: str = Field(default="ap-south-1")
    AWS_ACCESS_KEY_ID: Optional[str] = Field(default=None)
    AWS_SECRET_ACCESS_KEY: Optional[str] = Field(default=None)
    AWS_SESSION_TOKEN: Optional[str] = Field(default=None)

    # ------------------------------------------------------------------
    # Storage & Database provider
    # Options: "aws" (uses real S3 & DynamoDB or LocalStack) | "mock" (in-memory)
    # ------------------------------------------------------------------
    STORAGE_PROVIDER: Literal["aws", "mock"] = Field(default="aws")

    # ------------------------------------------------------------------
    # S3
    # ------------------------------------------------------------------
    S3_BUCKET_NAME: str = Field(default="vayu-drishti-reports")
    S3_SIGNED_URL_EXPIRY_SECONDS: int = Field(default=3600)

    # ------------------------------------------------------------------
    # DynamoDB table names
    # ------------------------------------------------------------------
    DYNAMODB_TABLE_DUST_REPORTS: str = Field(default="DustReports")
    DYNAMODB_TABLE_INCIDENT_CASES: str = Field(default="IncidentCases")
    DYNAMODB_TABLE_REVIEW_DECISIONS: str = Field(default="ReviewDecisions")
    DYNAMODB_TABLE_AUDIT_EVENTS: str = Field(default="AuditEvents")

    # ------------------------------------------------------------------
    # Vision / AI provider
    # Allowed values: "bedrock" | "openai" | "mock"
    # ------------------------------------------------------------------
    VISION_PROVIDER: Literal["bedrock", "openai", "mock"] = Field(default="mock")

    # Bedrock
    BEDROCK_MODEL_ID: str = Field(default="anthropic.claude-3-haiku-20240307-v1:0")
    BEDROCK_REGION: str = Field(default="ap-south-1")  # e.g. ap-south-1 or us-east-1

    # OpenAI (fallback)
    OPENAI_API_KEY: str = Field(default="")
    OPENAI_MODEL: str = Field(default="gpt-4o-mini")

    # ------------------------------------------------------------------
    # Geo / nearby-report search
    # ------------------------------------------------------------------
    GEO_NEARBY_RADIUS_KM: float = Field(default=2.0)
    GEO_NEARBY_TIME_WINDOW_DAYS: int = Field(default=30)

    # ------------------------------------------------------------------
    # Open-Meteo (free weather API — no key required)
    # ------------------------------------------------------------------
    WEATHER_API_BASE_URL: str = Field(default="https://api.open-meteo.com/v1")
    WEATHER_MOCK_FALLBACK: bool = Field(default=False)

    # ------------------------------------------------------------------
    # CORS (for the React/Vite frontend)
    # ------------------------------------------------------------------
    CORS_ORIGINS: list[str] = Field(
        default=["http://localhost:5173", "http://localhost:3000"]
    )

    # ------------------------------------------------------------------
    # Validators
    # ------------------------------------------------------------------
    @field_validator("STORAGE_PROVIDER", mode="before")
    @classmethod
    def normalise_storage_provider(cls, v: str) -> str:
        normalised = str(v).strip().lower()
        if normalised in {"s3", "dynamodb", "aws", "cloud", "production"}:
            return "aws"
        if normalised in {"mock", "memory", "in-memory", "local_mock"}:
            return "mock"
        return "aws"

    @field_validator("VISION_PROVIDER", mode="before")
    @classmethod
    def normalise_vision_provider(cls, v: str) -> str:
        normalised = str(v).strip().lower()
        allowed = {"bedrock", "openai", "mock"}
        if normalised not in allowed:
            raise ValueError(
                f"VISION_PROVIDER must be one of {allowed}; got '{v}'"
            )
        return normalised

    @field_validator("LOG_LEVEL", mode="before")
    @classmethod
    def normalise_log_level(cls, v: str) -> str:
        return str(v).strip().upper()

    # ------------------------------------------------------------------
    # Derived helpers (not env vars)
    # ------------------------------------------------------------------

    @property
    def aws_endpoint_url(self) -> str | None:
        """
        Returns the LocalStack endpoint URL when USE_LOCALSTACK is True,
        otherwise None (→ boto3 uses real AWS).
        """
        return self.LOCALSTACK_ENDPOINT if self.USE_LOCALSTACK else None

    @property
    def boto3_kwargs(self) -> dict:
        """
        Common kwargs to pass to every boto3.client() / boto3.resource() call.
        Includes endpoint_url only when LocalStack is active.
        Omits explicit access keys when not set so boto3 uses standard AWS IAM
        credential provider chains in AWS Console (App Runner, ECS, Lambda, EC2).
        """
        kwargs: dict = {
            "region_name": self.AWS_REGION,
        }
        if self.USE_LOCALSTACK:
            kwargs["endpoint_url"] = self.LOCALSTACK_ENDPOINT
            kwargs["aws_access_key_id"] = self.AWS_ACCESS_KEY_ID or "test"
            kwargs["aws_secret_access_key"] = self.AWS_SECRET_ACCESS_KEY or "test"
        else:
            if self.AWS_ACCESS_KEY_ID and self.AWS_ACCESS_KEY_ID.strip():
                kwargs["aws_access_key_id"] = self.AWS_ACCESS_KEY_ID.strip()
            if self.AWS_SECRET_ACCESS_KEY and self.AWS_SECRET_ACCESS_KEY.strip():
                kwargs["aws_secret_access_key"] = self.AWS_SECRET_ACCESS_KEY.strip()
            if self.AWS_SESSION_TOKEN and self.AWS_SESSION_TOKEN.strip():
                kwargs["aws_session_token"] = self.AWS_SESSION_TOKEN.strip()

        return kwargs

    class Config:
        # Allow loading from a .env file in the project root
        env_file = ".env"
        env_file_encoding = "utf-8"
        # Ignore unknown keys in .env — keeps local overrides safe
        extra = "ignore"
        case_sensitive = True


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """
    Return the cached Settings singleton.

    Usage:
        from config import get_settings
        settings = get_settings()
        print(settings.USE_LOCALSTACK)

    In FastAPI dependency injection:
        from fastapi import Depends
        from config import Settings, get_settings

        @router.get("/health")
        def health(cfg: Settings = Depends(get_settings)):
            return {"version": cfg.APP_VERSION}
    """
    return Settings()


# ---------------------------------------------------------------------------
# Module-level convenience alias
# ---------------------------------------------------------------------------
settings: Settings = get_settings()
