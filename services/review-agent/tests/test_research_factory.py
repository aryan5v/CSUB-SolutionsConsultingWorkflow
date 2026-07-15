"""Focused composition tests for fail-closed official-domain research wiring."""

from __future__ import annotations

import unittest
from unittest.mock import patch

import _bootstrap  # noqa: F401

from review_agent.adapters.model import DeterministicModelClient
from review_agent.api import LocalReviewApi
from review_agent.config import AppConfig
from review_agent.research import (
    GuardedHttpTransport,
    SystemResolver,
    VendorResearchService,
    build_research_provider,
)


class ResearchProviderFactoryTests(unittest.TestCase):
    def test_fixture_mode_has_no_provider_and_performs_no_network_setup(self) -> None:
        with patch(
            "review_agent.research.factory.GuardedHttpTransport",
            side_effect=AssertionError("fixture mode must not build a transport"),
        ):
            provider = build_research_provider(AppConfig(use_local_fakes=True))
            api = LocalReviewApi(config=AppConfig(use_local_fakes=True), seed_demo=False)

        self.assertIsNone(provider)
        self.assertIsNone(api.research_provider)
        self.assertIsNone(api._vendor.research_provider)

    def test_live_mode_builds_and_exposes_guarded_provider(self) -> None:
        config = AppConfig(use_local_fakes=False)
        api = LocalReviewApi(
            config=config,
            model_client=DeterministicModelClient(),
            seed_demo=False,
        )

        provider = api.research_provider
        self.assertIsInstance(provider, VendorResearchService)
        self.assertIsInstance(provider._transport, GuardedHttpTransport)
        self.assertIsInstance(provider._resolver, SystemResolver)
        self.assertIs(api._vendor.research_provider, provider)

    def test_live_mode_rejects_explicit_none(self) -> None:
        with self.assertRaisesRegex(ValueError, "live mode requires"):
            LocalReviewApi(
                config=AppConfig(use_local_fakes=False),
                model_client=DeterministicModelClient(),
                research_provider=None,
                seed_demo=False,
            )

    def test_live_factory_failure_propagates_without_fixture_fallback(self) -> None:
        failure = RuntimeError("invalid research policy")
        with patch(
            "review_agent.research.factory.ResearchPolicy.from_env",
            side_effect=failure,
        ):
            with self.assertRaisesRegex(RuntimeError, "invalid research policy"):
                LocalReviewApi(
                    config=AppConfig(use_local_fakes=False),
                    model_client=DeterministicModelClient(),
                    seed_demo=False,
                )


if __name__ == "__main__":
    unittest.main()
