"""Environment-driven configuration.

Account, region, profile, resource names, and model IDs are configurable and
never hard-coded (AGENTS.md, PRD sec 7). No secrets are read here; connector
credentials live in AWS Secrets Manager and are resolved at the write boundary,
not in application config.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ModelConfig:
    """Bedrock model/inference-profile IDs, discovered and pinned per account.

    Defaults are ``None`` so the local slice never assumes a specific account's
    model access. Wednesday pins real IDs from ``bedrock list-foundation-models``.
    """

    reasoning_model_id: str | None = None
    fallback_model_id: str | None = None
    extraction_model_id: str | None = None
    embedding_model_id: str | None = None
    guardrail_id: str | None = None


@dataclass(frozen=True, slots=True)
class AwsConfig:
    region: str = "us-west-2"
    profile: str | None = None
    raw_bucket: str | None = None
    normalized_bucket: str | None = None
    cases_table: str | None = None
    audit_table: str | None = None


@dataclass(frozen=True, slots=True)
class AppConfig:
    app_env: str = "development"
    use_local_fakes: bool = True
    aws: AwsConfig = AwsConfig()
    model: ModelConfig = ModelConfig()

    @classmethod
    def from_env(cls) -> "AppConfig":
        app_env = os.environ.get("APP_ENV", "development")
        # Local fakes are the default until an approved AWS environment is
        # recorded (PRD open questions). Set USE_LOCAL_FAKES=false to opt in.
        use_local_fakes = os.environ.get("USE_LOCAL_FAKES", "true").lower() != "false"
        return cls(
            app_env=app_env,
            use_local_fakes=use_local_fakes,
            aws=AwsConfig(
                region=os.environ.get("AWS_REGION", "us-west-2"),
                profile=os.environ.get("AWS_PROFILE") or None,
                raw_bucket=os.environ.get("RAW_BUCKET") or None,
                normalized_bucket=os.environ.get("NORMALIZED_BUCKET") or None,
                cases_table=os.environ.get("CASES_TABLE") or None,
                audit_table=os.environ.get("AUDIT_TABLE") or None,
            ),
            model=ModelConfig(
                reasoning_model_id=os.environ.get("BEDROCK_REASONING_MODEL_ID") or None,
                fallback_model_id=os.environ.get("BEDROCK_FALLBACK_MODEL_ID") or None,
                extraction_model_id=os.environ.get("BEDROCK_EXTRACTION_MODEL_ID") or None,
                embedding_model_id=os.environ.get("BEDROCK_EMBEDDING_MODEL_ID") or None,
                guardrail_id=os.environ.get("BEDROCK_GUARDRAIL_ID") or None,
            ),
        )
