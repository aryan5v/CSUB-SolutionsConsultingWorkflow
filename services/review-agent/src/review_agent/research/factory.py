"""Centralized factory for the official-domain vendor research provider (#44).

The provider is wired exactly once, from application configuration, so the
guarded live path and the local fixture path both stay honest and testable:

* **Live AWS mode** (``USE_LOCAL_FAKES=false``) always receives a real
  :class:`~review_agent.research.service.VendorResearchService` backed by
  :class:`~review_agent.research.service.GuardedHttpTransport`,
  :class:`~review_agent.research.service.SystemResolver`, and
  :meth:`~review_agent.research.policy.ResearchPolicy.from_env`. If construction
  fails, the exception propagates: a live-mode startup/configuration failure must
  never silently downgrade to "research not performed" (AGENTS.md fail-closed).

* **Local/fixture mode** (``USE_LOCAL_FAKES`` default ``true``) explicitly
  returns ``None`` -- and callers label it as such -- so
  :class:`~review_agent.vendor.service.VendorBackend` records research as *not
  performed* rather than fabricating findings or reaching the network. Fixture
  mode never constructs a live transport and never performs network I/O.

Keeping this decision in one place means neither ``LocalReviewApi`` nor the
Lambda ``restore_api`` path can accidentally construct the backend without a
provider in live mode.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .policy import ResearchPolicy
from .service import GuardedHttpTransport, SystemResolver, VendorResearchService

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ..config import AppConfig
    from .service import VendorResearchProvider


def build_research_provider(config: AppConfig) -> VendorResearchProvider | None:
    """Return the research provider for ``config``.

    Live AWS mode returns a guarded :class:`VendorResearchService`; local/fixture
    mode returns ``None`` (research explicitly not performed). Any failure to
    construct the live provider propagates rather than degrading to ``None``.
    """

    if config.use_local_fakes:
        return None
    return VendorResearchService(
        transport=GuardedHttpTransport(),
        resolver=SystemResolver(),
        policy=ResearchPolicy.from_env(),
    )
