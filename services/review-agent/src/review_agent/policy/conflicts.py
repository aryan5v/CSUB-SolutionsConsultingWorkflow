"""Conflict registry and disputed thresholds (FR-3, PRD open questions).

When supplied institutional sources disagree on a threshold, the prototype
records the disagreement and escalates cases that fall in the disputed band. It
never lets a model pick a value. Thresholds here are labeled ASSUMPTION until a
partner confirms them; the numbers are placeholders for the disputed *bands*,
not authoritative policy.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..contracts.common import Conflict, ConflictPosition, SourceCoordinates


@dataclass(frozen=True, slots=True)
class DisputedThreshold:
    """A single numeric threshold that sources disagree on.

    A case value strictly below ``min(bounds)`` or at/above ``max(bounds)`` is
    unambiguous. A value inside ``[min, max)`` is disputed and escalates.
    """

    topic: str
    field_name: str  # attribute of PolicyInputs this threshold reads
    positions: tuple[ConflictPosition, ...]

    @property
    def lower_bound(self) -> float:
        return min(float(p.value) for p in self.positions)

    @property
    def upper_bound(self) -> float:
        return max(float(p.value) for p in self.positions)

    def is_disputed_value(self, value: float) -> bool:
        return self.lower_bound <= value < self.upper_bound

    def as_conflict(self) -> Conflict:
        return Conflict(
            conflict_id=f"conflict-{self.topic}",
            topic=self.topic,
            positions=list(self.positions),
        )


@dataclass(slots=True)
class ConflictRegistry:
    """Holds disputed thresholds and any resolved overrides."""

    disputed_thresholds: list[DisputedThreshold] = field(default_factory=list)
    resolved: dict[str, str] = field(default_factory=dict)  # topic -> resolved value

    def disputes_for(self, inputs_dict: dict) -> list[Conflict]:
        """Return unresolved conflicts triggered by the given input values."""
        found: list[Conflict] = []
        for threshold in self.disputed_thresholds:
            if threshold.topic in self.resolved:
                continue
            value = inputs_dict.get(threshold.field_name)
            if value is None:
                continue
            if threshold.is_disputed_value(float(value)):
                found.append(threshold.as_conflict())
        return found


def _position(value: str, source_id: str, note: str, precedence: int) -> ConflictPosition:
    return ConflictPosition(
        value=value,
        source=SourceCoordinates(source_id=source_id, filename=note),
        precedence=precedence,
    )


def default_conflict_registry() -> ConflictRegistry:
    """ASSUMPTION bands for thresholds the PRD lists as open questions.

    Sources are placeholder manifest ids; real coordinates are filled when the
    partner-confirmed values arrive. Until then, values in the disputed band
    escalate to a human.
    """
    return ConflictRegistry(
        disputed_thresholds=[
            DisputedThreshold(
                topic="cost_review_threshold_usd",
                field_name="estimated_cost_usd",
                positions=(
                    _position("25000", "src:risk-review-process", "formal process (draft)", 2),
                    _position("50000", "src:discovery-call", "discovery statement", 4),
                ),
            ),
            DisputedThreshold(
                topic="user_count_review_threshold",
                field_name="expected_users",
                positions=(
                    _position("250", "src:decision-tree", "decision-tree draft", 3),
                    _position("1000", "src:discovery-call", "discovery statement", 4),
                ),
            ),
        ]
    )
