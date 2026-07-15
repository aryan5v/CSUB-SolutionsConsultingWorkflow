"""Immutable profile-version lifecycle and deterministic fixture evaluation."""

from __future__ import annotations

import datetime
import re
from dataclasses import replace
from typing import TYPE_CHECKING, Any, Callable, Iterable

from ..contracts.vendor import (
    DEFAULT_WORKSPACE_ID,
    ProfileStatus,
    ReviewCriterion,
    ReviewProfileVersion,
)

if TYPE_CHECKING:
    from ..vendor.repository import VendorRepository

_STABLE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{1,127}$")


class ProfileError(ValueError):
    pass


class ReviewProfileService:
    def __init__(
        self,
        repository: VendorRepository,
        *,
        workspace_id: str = DEFAULT_WORKSPACE_ID,
        clock: Callable[[], datetime.datetime] | None = None,
    ) -> None:
        self.repository = repository
        self.workspace_id = workspace_id
        self._clock = clock or (lambda: datetime.datetime.now(datetime.timezone.utc))

    def create_draft(
        self, profile_key: str, criteria: Iterable[ReviewCriterion | dict[str, Any]]
    ) -> ReviewProfileVersion:
        key = self._text(profile_key, "profile_key")
        existing = [profile for profile in self.list_versions(key)]
        version = max((profile.version for profile in existing), default=0) + 1
        profile = ReviewProfileVersion(
            profile_version_id=f"profile-{key}-{version:03d}",
            profile_key=key,
            version=version,
            criteria=self._criteria(criteria),
            created_at=self._now(),
            workspace_id=self.workspace_id,
        )
        self.repository.put(
            "profile", profile.profile_version_id, profile, workspace_id=self.workspace_id
        )
        return profile

    def update_draft(
        self,
        profile_version_id: str,
        criteria: Iterable[ReviewCriterion | dict[str, Any]],
    ) -> ReviewProfileVersion:
        profile = self.get(profile_version_id)
        if profile.status is not ProfileStatus.DRAFT:
            raise ProfileError("activated profile versions are immutable")
        updated = replace(profile, criteria=self._criteria(criteria), fixture_tested_at=None)
        self.repository.put(
            "profile", updated.profile_version_id, updated, workspace_id=self.workspace_id
        )
        return updated

    def fixture_test(
        self,
        profile_version_id: str,
        fixtures: Iterable[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        profile = self.get(profile_version_id)
        if profile.status is not ProfileStatus.DRAFT:
            raise ProfileError("activated profile versions are immutable")
        requirement_ids = {criterion.requirement_id for criterion in profile.criteria}
        supplied = list(fixtures or [{}])
        results: list[dict[str, Any]] = []
        for index, fixture in enumerate(supplied, start=1):
            if not isinstance(fixture, dict):
                raise ProfileError("each fixture must be an object")
            allowed = {
                "covered_requirement_ids",
                "answered_requirement_ids",
                "expected_unresolved_requirement_ids",
            }
            if set(fixture) - allowed:
                raise ProfileError("fixture contains unsupported fields")
            covered = self._id_set(fixture.get("covered_requirement_ids", []), requirement_ids)
            answered = self._id_set(fixture.get("answered_requirement_ids", []), requirement_ids)
            unresolved = sorted(requirement_ids - covered - answered)
            expected = fixture.get("expected_unresolved_requirement_ids", unresolved)
            if not isinstance(expected, list) or not all(isinstance(item, str) for item in expected):
                raise ProfileError("expected_unresolved_requirement_ids must be strings")
            passed = unresolved == sorted(expected)
            results.append(
                {
                    "fixture": index,
                    "passed": passed,
                    "unresolved_requirement_ids": unresolved,
                }
            )
        passed = all(result["passed"] for result in results)
        if passed:
            profile = replace(profile, fixture_tested_at=self._now())
            self.repository.put(
                "profile", profile.profile_version_id, profile, workspace_id=self.workspace_id
            )
        return {
            "profile_version_id": profile_version_id,
            "passed": passed,
            "results": results,
        }

    def activate(self, profile_version_id: str) -> ReviewProfileVersion:
        profile = self.get(profile_version_id)
        if profile.status is ProfileStatus.ACTIVATED:
            self.repository.set_active_profile(
                profile.profile_key, profile.profile_version_id, workspace_id=self.workspace_id
            )
            return profile
        if profile.fixture_tested_at is None:
            raise ProfileError("profile must pass fixture tests before activation")
        activated = replace(profile, status=ProfileStatus.ACTIVATED)
        self.repository.put(
            "profile", activated.profile_version_id, activated, workspace_id=self.workspace_id
        )
        self.repository.set_active_profile(
            activated.profile_key,
            activated.profile_version_id,
            workspace_id=self.workspace_id,
        )
        return activated

    def rollback(self, profile_key: str, profile_version_id: str) -> ReviewProfileVersion:
        profile = self.get(profile_version_id)
        if profile.profile_key != profile_key:
            raise ProfileError("rollback profile key does not match version")
        if profile.status is not ProfileStatus.ACTIVATED:
            raise ProfileError("rollback target must be a previously activated immutable version")
        self.repository.set_active_profile(
            profile_key, profile.profile_version_id, workspace_id=self.workspace_id
        )
        return profile

    def active(self, profile_key: str) -> ReviewProfileVersion:
        profile_id = self.repository.get_active_profile_id(
            profile_key, workspace_id=self.workspace_id
        )
        if profile_id is None:
            raise ProfileError(f"no active profile for {profile_key!r}")
        return self.get(profile_id)

    def active_profiles(self) -> list[ReviewProfileVersion]:
        keys = sorted({profile.profile_key for profile in self.list_versions()})
        active: list[ReviewProfileVersion] = []
        for key in keys:
            profile_id = self.repository.get_active_profile_id(
                key, workspace_id=self.workspace_id
            )
            if profile_id is not None:
                active.append(self.get(profile_id))
        return active

    def get(self, profile_version_id: str) -> ReviewProfileVersion:
        value = self.repository.get(
            "profile", profile_version_id, workspace_id=self.workspace_id
        )
        if not isinstance(value, ReviewProfileVersion):
            raise ProfileError("profile version not found")
        return value

    def list_versions(self, profile_key: str | None = None) -> list[ReviewProfileVersion]:
        profiles = [
            item
            for item in self.repository.list("profile", workspace_id=self.workspace_id)
            if isinstance(item, ReviewProfileVersion)
        ]
        if profile_key is not None:
            profiles = [item for item in profiles if item.profile_key == profile_key]
        return sorted(profiles, key=lambda item: (item.profile_key, item.version))

    def _criteria(
        self, values: Iterable[ReviewCriterion | dict[str, Any]]
    ) -> tuple[ReviewCriterion, ...]:
        criteria: list[ReviewCriterion] = []
        for raw in values:
            if isinstance(raw, ReviewCriterion):
                criterion = raw
            elif isinstance(raw, dict):
                allowed = {
                    "requirement_id",
                    "question",
                    "source_citation",
                    "expected_evidence",
                    "output_fields",
                    "remediation_guidance",
                }
                if set(raw) != allowed:
                    raise ProfileError("criterion fields must exactly match the contract")
                citation = raw["source_citation"]
                if not isinstance(citation, dict) or not isinstance(citation.get("source_id"), str):
                    raise ProfileError("criterion requires a source citation with source_id")
                expected = raw["expected_evidence"]
                outputs = raw["output_fields"]
                if not isinstance(expected, list) or not all(isinstance(v, str) and v for v in expected):
                    raise ProfileError("expected_evidence must be non-empty strings")
                if not isinstance(outputs, list) or not all(isinstance(v, str) and v for v in outputs):
                    raise ProfileError("output_fields must be non-empty strings")
                criterion = ReviewCriterion(
                    requirement_id=self._text(raw["requirement_id"], "requirement_id"),
                    question=self._text(raw["question"], "question"),
                    source_citation=dict(citation),
                    expected_evidence=tuple(expected),
                    output_fields=tuple(outputs),
                    remediation_guidance=self._text(
                        raw["remediation_guidance"], "remediation_guidance"
                    ),
                )
            else:
                raise ProfileError("criterion must be an object")
            if not _STABLE_ID.fullmatch(criterion.requirement_id):
                raise ProfileError("requirement_id must be a stable identifier")
            if not criterion.source_citation.get("source_id"):
                raise ProfileError("criterion source citation is required")
            criteria.append(criterion)
        if not criteria:
            raise ProfileError("profile must contain at least one criterion")
        ids = [criterion.requirement_id for criterion in criteria]
        if len(ids) != len(set(ids)):
            raise ProfileError("requirement_id values must be unique within a profile")
        return tuple(criteria)

    @staticmethod
    def _id_set(value: object, allowed: set[str]) -> set[str]:
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise ProfileError("fixture requirement identifiers must be strings")
        result = set(value)
        if not result <= allowed:
            raise ProfileError("fixture references unknown requirement identifiers")
        return result

    @staticmethod
    def _text(value: object, field_name: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ProfileError(f"{field_name} is required")
        return value.strip()

    def _now(self) -> str:
        value = self._clock()
        if value.tzinfo is None:
            raise ProfileError("clock must return a timezone-aware datetime")
        return value.astimezone(datetime.timezone.utc).isoformat()
