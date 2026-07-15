"""Live Bedrock smoke check (manual, not part of CI).

Drives the real ``BedrockModelClient`` against the pinned Claude Sonnet
inference profile in us-west-2 and runs one specialist node through it. Requires
AWS credentials with ``bedrock:InvokeModel`` on the pinned profile. It never
writes to any system and prints only non-sensitive, synthetic output.

    USE_LOCAL_FAKES=false AWS_REGION=us-west-2 \
        python services/review-agent/scripts/smoke_bedrock.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from review_agent.adapters.model import build_model_client  # noqa: E402
from review_agent.config import AppConfig  # noqa: E402
from review_agent.policy.conflicts import default_conflict_registry  # noqa: E402
from review_agent.policy.engine import build_inputs, evaluate  # noqa: E402
from review_agent.policy.rules import default_ruleset  # noqa: E402
from review_agent.samples import medium_risk_case  # noqa: E402
from review_agent.specialists.security import run_security  # noqa: E402


def main() -> int:
    os.environ.setdefault("USE_LOCAL_FAKES", "false")
    config = AppConfig.from_env()
    if config.use_local_fakes:
        print("USE_LOCAL_FAKES is true; set it to false to exercise live Bedrock.")
        return 1

    model = build_model_client(config)
    print(f"client:   {type(model).__name__}")
    print(f"model_id: {config.model.reasoning_model_id}")
    print(f"region:   {config.aws.region}")

    case = medium_risk_case()
    policy = evaluate(
        build_inputs(case, is_approved_software=False),
        default_ruleset(),
        default_conflict_registry(),
    )
    result = run_security(case, policy, model)
    print("\n== security specialist (live) ==")
    print(f"  summary:   {result['summary'][:200] or '(model returned no summary)'}")
    print(f"  findings:  {len(result['findings'])}")
    print(f"  citations: {len(result['citations'])} (grounded in deterministic policy)")
    print("\nLive Bedrock smoke OK.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
