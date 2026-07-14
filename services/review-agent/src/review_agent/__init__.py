"""CSUB Technology Review Agent (Python workspace).

Ingestion, deterministic policy, bounded LLM orchestration, mock ServiceNow
write-back, and structured audit for the review workflow. Every AWS/external
boundary is an interface with a local fake; the Tuesday slice runs with no live
AWS. See docs/decisions/0003-review-agent-local-slice.md.
"""

from __future__ import annotations

__version__ = "0.1.0"
