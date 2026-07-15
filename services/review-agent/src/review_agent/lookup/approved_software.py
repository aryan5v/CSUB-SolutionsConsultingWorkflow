"""Approved-software lookup with disclosed match method (FR-2).

Deterministic tiers run in order and the first tier that yields candidates
wins: exact -> alias/short-name -> vendor+product -> fuzzy -> semantic. Fuzzy
and semantic candidates are returned with ``requires_confirmation=True``; a
model must never auto-confirm them. Semantic search needs an embedding provider
and is skipped (with a disclosure) when none is configured, which is the default
in the local slice.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from ..contracts.common import SourceCoordinates
from ..contracts.software import ApprovedSoftwareRecord, MatchMethod, SoftwareMatch

# Provider returning (record_id, score in [0,1]) semantic candidates. Injected
# Wednesday (Titan embeddings + S3 Vectors); None in the local slice.
SemanticProvider = Callable[[str, Iterable[ApprovedSoftwareRecord]], list[tuple[str, float]]]

_FUZZY_THRESHOLD = 0.82


def _normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def _tokens(text: str) -> set[str]:
    return {t for t in re.split(r"[^a-z0-9]+", text.lower()) if t}


@dataclass(slots=True)
class LookupResult:
    matches: list[SoftwareMatch] = field(default_factory=list)
    disclosures: list[str] = field(default_factory=list)


class ApprovedSoftwareIndex:
    def __init__(
        self,
        records: list[ApprovedSoftwareRecord],
        *,
        semantic_provider: SemanticProvider | None = None,
    ) -> None:
        self._records = records
        self._by_id = {r.record_id: r for r in records}
        self._semantic_provider = semantic_provider
        self._exact: dict[str, list[str]] = {}
        self._alias: dict[str, list[str]] = {}
        for record in records:
            self._exact.setdefault(_normalize(record.canonical_name), []).append(record.record_id)
            alias_names = list(record.aliases)
            if record.short_name:
                alias_names.append(record.short_name)
            for alias in alias_names:
                self._alias.setdefault(_normalize(alias), []).append(record.record_id)

    def lookup(self, product_name: str, vendor_name: str | None = None) -> LookupResult:
        norm = _normalize(product_name)

        exact = self._exact.get(norm, [])
        if exact:
            return LookupResult(matches=self._build(exact, MatchMethod.EXACT, 1.0))

        alias = self._alias.get(norm, [])
        if alias:
            return LookupResult(matches=self._build(alias, MatchMethod.ALIAS, 0.98))

        if vendor_name:
            vp = self._vendor_product(product_name, vendor_name)
            if vp:
                return LookupResult(matches=vp)

        fuzzy = self._fuzzy(product_name)
        if fuzzy:
            return LookupResult(matches=fuzzy)

        return self._semantic(product_name)

    # -- tiers -----------------------------------------------------------------

    def _vendor_product(self, product_name: str, vendor_name: str) -> list[SoftwareMatch]:
        product_tokens = _tokens(product_name)
        vendor_norm = _normalize(vendor_name)
        matches: list[SoftwareMatch] = []
        for record in self._records:
            if _normalize(record.vendor) != vendor_norm:
                continue
            if product_tokens & _tokens(record.canonical_name):
                matches.append(self._match(record, MatchMethod.VENDOR_PRODUCT, 0.9))
        return matches

    def _fuzzy(self, product_name: str) -> list[SoftwareMatch]:
        from difflib import SequenceMatcher

        norm = _normalize(product_name)
        scored: list[SoftwareMatch] = []
        for record in self._records:
            ratio = SequenceMatcher(None, norm, _normalize(record.canonical_name)).ratio()
            if ratio >= _FUZZY_THRESHOLD:
                scored.append(self._match(record, MatchMethod.FUZZY, ratio))
        scored.sort(key=lambda m: m.score, reverse=True)
        return scored

    def _semantic(self, product_name: str) -> LookupResult:
        if self._semantic_provider is None:
            return LookupResult(
                disclosures=[
                    "semantic search skipped: no embedding provider configured "
                    "(local slice); configure Titan embeddings on Wednesday"
                ]
            )
        candidates = self._semantic_provider(product_name, self._records)
        matches = [
            self._match(self._by_id[rid], MatchMethod.SEMANTIC, score)
            for rid, score in candidates
            if rid in self._by_id
        ]
        return LookupResult(matches=matches)

    # -- helpers ---------------------------------------------------------------

    def _build(self, ids: list[str], method: MatchMethod, score: float) -> list[SoftwareMatch]:
        return [self._match(self._by_id[rid], method, score) for rid in ids]

    def _match(self, record: ApprovedSoftwareRecord, method: MatchMethod, score: float) -> SoftwareMatch:
        ref = record.source_coordinates or SourceCoordinates(
            source_id="src:approved-software-export", filename=record.record_id
        )
        return SoftwareMatch(
            record_id=record.record_id,
            match_method=method,
            score=score,
            source_row_ref=ref,
            canonical_name=record.canonical_name,
        )
