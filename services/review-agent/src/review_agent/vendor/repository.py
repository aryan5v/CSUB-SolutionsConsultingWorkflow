"""Persistence interfaces and deterministic in-memory implementation.

The protocol uses workspace-qualified reads and whole-record writes so a future
DynamoDB adapter can use partition keys plus conditional expressions without
changing domain services.
"""

from __future__ import annotations

import copy
from collections import defaultdict
from typing import Protocol, TypeVar, runtime_checkable

from ..contracts.vendor import (
    CoverageItem,
    EvidenceArtifact,
    IntegrationEvent,
    ReviewProfileVersion,
    ReviewRun,
    Submission,
    ThreadMessage,
    Vendor,
    VendorCase,
    VendorContact,
    VendorInvite,
    VendorProduct,
)

Record = TypeVar("Record")


@runtime_checkable
class VendorRepository(Protocol):
    def put(self, kind: str, record_id: str, record: object, *, workspace_id: str) -> None: ...

    def get(self, kind: str, record_id: str, *, workspace_id: str) -> object | None: ...

    def list(self, kind: str, *, workspace_id: str) -> list[object]: ...

    def delete(self, kind: str, record_id: str, *, workspace_id: str) -> None: ...

    def find_invite_by_token_hash(
        self, token_hash: str, *, workspace_id: str
    ) -> VendorInvite | None: ...

    def set_active_profile(
        self, profile_key: str, profile_version_id: str, *, workspace_id: str
    ) -> None: ...

    def get_active_profile_id(self, profile_key: str, *, workspace_id: str) -> str | None: ...

    def set_current_run(self, case_id: str, run_id: str, *, workspace_id: str) -> None: ...

    def get_current_run_id(self, case_id: str, *, workspace_id: str) -> str | None: ...


class InMemoryVendorRepository:
    """Copy-on-read/write local persistence with strict workspace partitioning."""

    def __init__(self) -> None:
        self._records: dict[tuple[str, str], dict[str, object]] = defaultdict(dict)
        self._active_profiles: dict[tuple[str, str], str] = {}
        self._current_runs: dict[tuple[str, str], str] = {}

    def put(self, kind: str, record_id: str, record: object, *, workspace_id: str) -> None:
        actual_workspace = getattr(record, "workspace_id", None)
        if actual_workspace != workspace_id:
            raise ValueError("record workspace does not match repository partition")
        self._records[(workspace_id, kind)][record_id] = copy.deepcopy(record)

    def get(self, kind: str, record_id: str, *, workspace_id: str) -> object | None:
        value = self._records[(workspace_id, kind)].get(record_id)
        return copy.deepcopy(value)

    def list(self, kind: str, *, workspace_id: str) -> list[object]:
        records = self._records[(workspace_id, kind)]
        return [copy.deepcopy(records[key]) for key in sorted(records)]

    def delete(self, kind: str, record_id: str, *, workspace_id: str) -> None:
        self._records[(workspace_id, kind)].pop(record_id, None)

    def find_invite_by_token_hash(
        self, token_hash: str, *, workspace_id: str
    ) -> VendorInvite | None:
        for value in self._records[(workspace_id, "invite")].values():
            if isinstance(value, VendorInvite) and value.token_hash == token_hash:
                return copy.deepcopy(value)
        return None

    def set_active_profile(
        self, profile_key: str, profile_version_id: str, *, workspace_id: str
    ) -> None:
        self._active_profiles[(workspace_id, profile_key)] = profile_version_id

    def get_active_profile_id(self, profile_key: str, *, workspace_id: str) -> str | None:
        return self._active_profiles.get((workspace_id, profile_key))

    def set_current_run(self, case_id: str, run_id: str, *, workspace_id: str) -> None:
        self._current_runs[(workspace_id, case_id)] = run_id

    def get_current_run_id(self, case_id: str, *, workspace_id: str) -> str | None:
        return self._current_runs.get((workspace_id, case_id))


RECORD_KINDS: dict[type[object], str] = {
    Vendor: "vendor",
    VendorProduct: "product",
    VendorContact: "contact",
    VendorCase: "case",
    VendorInvite: "invite",
    Submission: "submission",
    EvidenceArtifact: "evidence",
    CoverageItem: "coverage",
    ReviewProfileVersion: "profile",
    ReviewRun: "run",
    IntegrationEvent: "event",
    ThreadMessage: "thread_message",
}
