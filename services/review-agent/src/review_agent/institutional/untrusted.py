"""Scan extracted document text for untrusted-content signals.

Every institutional document is treated as untrusted input (AGENTS.md, PRD
sec 7). This module only *detects and reports* two things:

1. Tracking or AI-provenance URLs, in particular ``chatgpt.com`` links and any
   URL carrying ``utm_source=chatgpt.com``. Such a parameter means the text was
   likely pasted from ChatGPT, so the surrounding claim cannot be treated as an
   authoritative institutional source and the link should not be fetched.
2. Instruction-like phrases that look like prompt injection.

It never follows, executes, or resolves anything it finds. Findings are surfaced
as warnings so a human can review them. Snippets are truncated and whitespace
collapsed so nothing large or sensitive is echoed.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass

_URL_RE = re.compile(r"https?://[^\s\"'<>()\[\]]+", re.IGNORECASE)

# Hosts whose presence signals AI provenance / tracking rather than an
# authoritative institutional source.
_TRACKING_HOSTS = ("chatgpt.com",)
_TRACKING_PARAMS = ("utm_source=chatgpt.com",)

# Instruction-like phrases. Matching one means "quarantine and flag", never
# "obey". Kept deliberately narrow to avoid flagging ordinary policy prose.
_INJECTION_PATTERNS = (
    r"ignore (?:all |the )?(?:previous|prior|above) instructions",
    r"disregard (?:the |all )?(?:previous|prior|above)",
    r"you are now\b",
    r"act as\b",
    r"system prompt\b",
    r"new instructions\s*:",
    r"override (?:your|the) (?:instructions|rules|guardrails)",
    r"do not (?:tell|inform) the (?:user|reviewer)",
)
_INJECTION_RE = re.compile("|".join(_INJECTION_PATTERNS), re.IGNORECASE)

_MAX_SNIPPET = 160


@dataclass(frozen=True, slots=True)
class UntrustedFinding:
    kind: str  # "tracking_url" | "prompt_injection"
    detail: str
    snippet: str

    def to_dict(self) -> dict:
        return asdict(self)


def _snippet(text: str, start: int, end: int) -> str:
    lo = max(0, start - 40)
    hi = min(len(text), end + 40)
    fragment = " ".join(text[lo:hi].split())
    if len(fragment) > _MAX_SNIPPET:
        fragment = fragment[:_MAX_SNIPPET] + "..."
    return fragment


def _is_tracking_url(url: str) -> str | None:
    lowered = url.lower()
    for host in _TRACKING_HOSTS:
        if re.search(rf"://(?:[^/]*\.)?{re.escape(host)}(?:[:/?#]|$)", lowered):
            return host
    for param in _TRACKING_PARAMS:
        if param in lowered:
            return param
    return None


def scan_untrusted_text(text: str | None) -> list[UntrustedFinding]:
    """Return findings for tracking URLs and injection-like phrases in ``text``.

    Returns an empty list for ``None`` or empty text. Detection only; nothing is
    fetched or executed.
    """

    if not text:
        return []

    findings: list[UntrustedFinding] = []

    for match in _URL_RE.finditer(text):
        url = match.group(0).rstrip(".,);]")
        hit = _is_tracking_url(url)
        if hit is not None:
            findings.append(
                UntrustedFinding(
                    kind="tracking_url",
                    detail=f"tracking/AI-provenance marker '{hit}' in URL",
                    snippet=_snippet(text, match.start(), match.end()),
                )
            )

    for match in _INJECTION_RE.finditer(text):
        findings.append(
            UntrustedFinding(
                kind="prompt_injection",
                detail=f"instruction-like phrase ignored: '{match.group(0).lower()}'",
                snippet=_snippet(text, match.start(), match.end()),
            )
        )

    return findings


def contains_tracking_url(text: str | None) -> bool:
    return any(f.kind == "tracking_url" for f in scan_untrusted_text(text))
