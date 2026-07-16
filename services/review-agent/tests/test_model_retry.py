"""Bounded retry/timeout behavior for model calls (issue #50)."""

from __future__ import annotations

import unittest

import _bootstrap  # noqa: F401

from review_agent.adapters.model import (
    ModelStructureError,
    RetryPolicy,
    invoke_structured,
)
from review_agent.observability.metrics import InMemoryMetricsSink

_VALID_REPLY = {
    "summary": "ok",
    "findings": [],
    "citations": [],
    "uncertainty": "",
}


class _FlakyModel:
    """Fails with a transient error a fixed number of times, then succeeds."""

    def __init__(self, failures: int, error_factory) -> None:
        self._remaining = failures
        self._error_factory = error_factory
        self.calls = 0

    def complete_json(self, *, system: str, prompt: str, context: dict) -> dict:
        self.calls += 1
        if self._remaining > 0:
            self._remaining -= 1
            raise self._error_factory()
        return dict(_VALID_REPLY)


class _AlwaysTransientModel:
    def __init__(self, error_factory) -> None:
        self._error_factory = error_factory
        self.calls = 0

    def complete_json(self, *, system: str, prompt: str, context: dict) -> dict:
        self.calls += 1
        raise self._error_factory()


class _SlowModel:
    """Simulates a hung call: sleeps past the configured timeout."""

    def __init__(self, delay_seconds: float) -> None:
        self._delay = delay_seconds
        self.calls = 0

    def complete_json(self, *, system: str, prompt: str, context: dict) -> dict:
        import time

        self.calls += 1
        time.sleep(self._delay)
        return dict(_VALID_REPLY)


class RetryPolicyTests(unittest.TestCase):
    def test_transient_failure_retries_then_succeeds(self) -> None:
        model = _FlakyModel(failures=2, error_factory=lambda: ConnectionError("reset"))
        sleeps: list[float] = []
        result = invoke_structured(
            model,
            system="sys",
            prompt="prompt",
            context={},
            retry_policy=RetryPolicy(max_attempts=3, base_delay_seconds=0, timeout_seconds=5),
        )
        self.assertEqual(result["summary"], "ok")
        self.assertEqual(result["_model"]["retry_count"], 2)
        self.assertEqual(model.calls, 3)

    def test_exhausted_retries_surface_as_reviewable_failure(self) -> None:
        model = _AlwaysTransientModel(error_factory=lambda: ConnectionError("down"))
        with self.assertRaises(ModelStructureError):
            invoke_structured(
                model,
                system="sys",
                prompt="prompt",
                context={},
                retry_policy=RetryPolicy(max_attempts=2, base_delay_seconds=0, timeout_seconds=5),
            )
        # One initial attempt-block (2 tries) plus one repair attempt-block (2
        # tries): bounded, not unbounded retrying.
        self.assertEqual(model.calls, 4)

    def test_timeout_is_bounded_and_retried(self) -> None:
        model = _SlowModel(delay_seconds=0.2)
        with self.assertRaises(ModelStructureError) as ctx:
            invoke_structured(
                model,
                system="sys",
                prompt="prompt",
                context={},
                retry_policy=RetryPolicy(max_attempts=2, base_delay_seconds=0, timeout_seconds=0.05),
            )
        self.assertIn("timeout", str(ctx.exception).lower())

    def test_non_transient_error_is_not_retried(self) -> None:
        model = _FlakyModel(failures=1, error_factory=lambda: ValueError("bad json"))
        # ValueError is treated as a structural failure (existing repair-pass
        # contract), not a transient retry -- the flaky model's second call is
        # the single repair attempt, not a retry of the first, and it succeeds.
        result = invoke_structured(
            model,
            system="sys",
            prompt="prompt",
            context={},
            retry_policy=RetryPolicy(max_attempts=3, base_delay_seconds=0, timeout_seconds=5),
        )
        self.assertEqual(result["_model"]["repair_passes"], 1)
        self.assertEqual(result["_model"]["retry_count"], 0)
        self.assertEqual(model.calls, 2)

    def test_emits_latency_and_retry_metrics(self) -> None:
        model = _FlakyModel(failures=1, error_factory=lambda: ConnectionError("reset"))
        sink = InMemoryMetricsSink()
        invoke_structured(
            model,
            system="sys",
            prompt="prompt",
            context={},
            retry_policy=RetryPolicy(max_attempts=3, base_delay_seconds=0, timeout_seconds=5),
            metrics=sink,
            metric_dimensions={"step": "security"},
        )
        self.assertIn("model.invoke.latency_ms", sink.names())
        self.assertEqual(sink.values_for("model.invoke.retry_count"), [1])
        record = next(r for r in sink.records if r["name"] == "model.invoke.retry_count")
        self.assertEqual(record["dimensions"]["step"], "security")

    def test_emits_failure_metric_on_exhausted_repair(self) -> None:
        model = _AlwaysTransientModel(error_factory=lambda: ConnectionError("down"))
        sink = InMemoryMetricsSink()
        with self.assertRaises(ModelStructureError):
            invoke_structured(
                model,
                system="sys",
                prompt="prompt",
                context={},
                retry_policy=RetryPolicy(max_attempts=1, base_delay_seconds=0, timeout_seconds=5),
                metrics=sink,
            )
        self.assertIn("model.invoke.failure", sink.names())


class RetryPolicyValidationTests(unittest.TestCase):
    """An unusable policy is rejected where it is built, not mid-call."""

    def test_max_attempts_below_one_is_rejected(self) -> None:
        # Zero attempts would skip the retry loop and surface as an
        # UnboundLocalError from a model call, far from the real mistake.
        with self.assertRaises(ValueError):
            RetryPolicy(max_attempts=0)

    def test_negative_base_delay_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            RetryPolicy(base_delay_seconds=-1.0)

    def test_non_positive_timeout_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            RetryPolicy(timeout_seconds=0)

    def test_a_single_attempt_is_valid(self) -> None:
        # max_attempts=1 means "no retries", which is a legitimate choice.
        self.assertEqual(RetryPolicy(max_attempts=1).max_attempts, 1)


if __name__ == "__main__":
    unittest.main()
