"""BedrockModelClient transport and JSON-parsing tests.

No network and no boto3: a fake ``converse`` client is injected so these run in
the stdlib-only CI gate. They cover request shaping (trust-boundary system
instruction, guardrail config, context fenced as data) and tolerant parsing of
fenced or prose-wrapped model replies.
"""

from __future__ import annotations

import unittest

import _bootstrap  # noqa: F401

from review_agent.adapters.model import (
    BedrockModelClient,
    DeterministicModelClient,
    build_model_client,
)
from review_agent.config import AppConfig, AwsConfig, ModelConfig


class _FakeConverse:
    """Records the request and returns a canned Converse response body."""

    def __init__(self, reply_text: str) -> None:
        self.reply_text = reply_text
        self.last_request: dict | None = None

    def converse(self, **kwargs):
        self.last_request = kwargs
        return {"output": {"message": {"content": [{"text": self.reply_text}]}}}


class BedrockRequestShapeTests(unittest.TestCase):
    def test_builds_converse_request_with_trust_boundary_and_context(self) -> None:
        fake = _FakeConverse('{"summary": "ok", "findings": []}')
        client = BedrockModelClient(
            model_id="us.anthropic.claude-sonnet-4-5-20250929-v1:0",
            region="us-west-2",
            client=fake,
        )
        out = client.complete_json(
            system="You summarize only; do not set risk tiers.",
            prompt="Summarize posture.",
            context={"task": "security_analysis", "product": "Acme"},
        )
        self.assertEqual(out, {"summary": "ok", "findings": []})
        req = fake.last_request
        self.assertEqual(req["modelId"], "us.anthropic.claude-sonnet-4-5-20250929-v1:0")
        # JSON-only instruction is appended to the caller's system prompt.
        self.assertIn("single JSON object", req["system"][0]["text"])
        self.assertIn("do not set risk tiers", req["system"][0]["text"])
        # Context is fenced as data, not merged into instructions.
        user_text = req["messages"][0]["content"][0]["text"]
        self.assertIn("data only", user_text)
        self.assertIn("security_analysis", user_text)
        self.assertEqual(req["inferenceConfig"]["temperature"], 0.0)
        self.assertNotIn("guardrailConfig", req)

    def test_guardrail_config_included_when_configured(self) -> None:
        fake = _FakeConverse("{}")
        client = BedrockModelClient(
            model_id="m",
            region="us-west-2",
            guardrail_id="gr-123",
            client=fake,
        )
        client.complete_json(system="s", prompt="p", context={})
        self.assertEqual(
            fake.last_request["guardrailConfig"],
            {"guardrailIdentifier": "gr-123", "guardrailVersion": "DRAFT"},
        )


class JsonParsingTests(unittest.TestCase):
    def test_parses_markdown_fenced_json(self) -> None:
        fake = _FakeConverse('```json\n{"a": 1}\n```')
        client = BedrockModelClient(model_id="m", region="r", client=fake)
        self.assertEqual(client.complete_json(system="s", prompt="p", context={}), {"a": 1})

    def test_parses_json_with_trailing_prose(self) -> None:
        fake = _FakeConverse('Here is the result: {"a": 2} — hope that helps!')
        client = BedrockModelClient(model_id="m", region="r", client=fake)
        self.assertEqual(client.complete_json(system="s", prompt="p", context={}), {"a": 2})

    def test_rejects_non_object_reply(self) -> None:
        fake = _FakeConverse("no json here at all")
        client = BedrockModelClient(model_id="m", region="r", client=fake)
        with self.assertRaises(ValueError):
            client.complete_json(system="s", prompt="p", context={})

    def test_rejects_json_array(self) -> None:
        fake = _FakeConverse("[1, 2, 3]")
        client = BedrockModelClient(model_id="m", region="r", client=fake)
        with self.assertRaises(ValueError):
            client.complete_json(system="s", prompt="p", context={})


class FactoryTests(unittest.TestCase):
    def test_local_fakes_returns_deterministic_client(self) -> None:
        config = AppConfig(use_local_fakes=True)
        self.assertIsInstance(build_model_client(config), DeterministicModelClient)

    def test_aws_mode_returns_bedrock_client_with_pinned_id(self) -> None:
        config = AppConfig(
            use_local_fakes=False,
            aws=AwsConfig(region="us-west-2"),
            model=ModelConfig(),  # uses the pinned Sonnet 4.5 default
        )
        client = build_model_client(config)
        self.assertIsInstance(client, BedrockModelClient)

    def test_aws_mode_requires_a_reasoning_model_id(self) -> None:
        config = AppConfig(
            use_local_fakes=False,
            model=ModelConfig(reasoning_model_id=None),
        )
        with self.assertRaises(ValueError):
            build_model_client(config)


if __name__ == "__main__":
    unittest.main()
