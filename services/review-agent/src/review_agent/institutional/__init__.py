"""Development-time institutional source normalization slice.

Classifies the supplied Box corpus, keeps institutional policy separate from
case/vendor evidence, blocks activation of draft or example sources, and flags
untrusted content (tracking URLs and instruction-like text). It reads no bytes
in its core API and commits no source content, normalized corpus, or hashes.
See ``services/review-agent/README.md`` and ADR 0007.
"""

from __future__ import annotations

from .classification import (
    Classification,
    ConfirmationStatus,
    CorpusMembership,
    SourceCategory,
    classify,
)
from .normalize import (
    ActivationBlockedError,
    CorpusNormalizationResult,
    InstitutionalSourceRecord,
    assert_activatable,
    normalize_corpus,
    normalize_source,
)
from .untrusted import UntrustedFinding, contains_tracking_url, scan_untrusted_text

__all__ = [
    "ActivationBlockedError",
    "Classification",
    "ConfirmationStatus",
    "CorpusMembership",
    "CorpusNormalizationResult",
    "InstitutionalSourceRecord",
    "SourceCategory",
    "UntrustedFinding",
    "assert_activatable",
    "classify",
    "contains_tracking_url",
    "normalize_corpus",
    "normalize_source",
    "scan_untrusted_text",
]
