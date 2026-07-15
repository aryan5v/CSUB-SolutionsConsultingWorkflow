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
    """Bedrock inference-profile IDs, pinned for us-west-2 and env-overridable.

    Defaults are cross-region US **system-defined inference profiles** (the
    ``us.*`` prefix routes across regions; they carry no account ID, so they are
    safe to commit and portable across the camp's sandbox accounts). Any value is
    overridable via the matching ``BEDROCK_*`` env var; embedding/guardrail stay
    ``None`` until retrieval and Guardrails land.

    Claude Sonnet 5 (``us.anthropic.claude-sonnet-5``) is the live frontier
    reasoning default, verified with a ``bedrock-runtime.converse`` probe in
    us-west-2 (``maxTokens=64``). Sonnet 5 rejects the deprecated ``temperature``
    inference field, so :class:`~review_agent.adapters.model.BedrockModelClient`
    omits temperature by default and always sends ``maxTokens`` explicitly.
    """

    # Claude Sonnet 5 — live frontier reasoning/specialist analysis and drafting.
    reasoning_model_id: str | None = "us.anthropic.claude-sonnet-5"
    # Amazon Nova Pro — capable fallback if the reasoning profile throttles.
    fallback_model_id: str | None = "us.amazon.nova-pro-v1:0"
    # Amazon Nova Lite — cheap structured extraction from uploaded evidence.
    extraction_model_id: str | None = "us.amazon.nova-lite-v1:0"
    embedding_model_id: str | None = None
    guardrail_id: str | None = None
    # Explicit output budget sent on every Converse call (never implicit).
    max_tokens: int = 1024


@dataclass(frozen=True, slots=True)
class AwsConfig:
    region: str = "us-west-2"
    profile: str | None = None
    raw_bucket: str | None = None
    normalized_bucket: str | None = None
    generated_bucket: str | None = None
    cases_table: str | None = None
    audit_table: str | None = None


@dataclass(frozen=True, slots=True)
class AppConfig:
    app_env: str = "development"
    use_local_fakes: bool = True
    aws: AwsConfig = AwsConfig()
    model: ModelConfig = ModelConfig()

    @classmethod
    def from_env(cls) -> AppConfig:
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
                generated_bucket=os.environ.get("GENERATED_BUCKET") or None,
                cases_table=os.environ.get("CASES_TABLE") or None,
                audit_table=os.environ.get("AUDIT_TABLE") or None,
            ),
            model=ModelConfig(
                reasoning_model_id=os.environ.get("BEDROCK_REASONING_MODEL_ID") or None,
                fallback_model_id=os.environ.get("BEDROCK_FALLBACK_MODEL_ID") or None,
                extraction_model_id=os.environ.get("BEDROCK_EXTRACTION_MODEL_ID") or None,
                embedding_model_id=os.environ.get("BEDROCK_EMBEDDING_MODEL_ID") or None,
                guardrail_id=os.environ.get("BEDROCK_GUARDRAIL_ID") or None,
                max_tokens=_positive_int_env("BEDROCK_MAX_TOKENS", 1024),
            ),
        )


def _positive_int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default
