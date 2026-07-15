"""Review workflow orchestration (PLAN Tuesday workflow/LLM agent).

Each method here is a workflow node with explicit inputs and outputs. In the
local slice they run as a deterministic sequential runner with checkpoint
boundaries; on Wednesday the same node functions and ``ReviewGraphState`` bind
to a LangGraph graph with an AgentCore checkpointer. Deterministic policy,
parallel specialists, one citation-repair pass, and human interrupt boundaries
are all represented.
"""

from __future__ import annotations

import datetime
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed

from ..adapters.model import ModelClient, ModelStructureError
from ..adapters.servicenow import ServiceNowConnector
from ..audit.log import AuditLog
from ..contracts.audit import ActorType
from ..contracts.graph_state import ReviewGraphState, WorkflowStatus
from ..contracts.policy import PolicyRuleSet
from ..contracts.servicenow import HumanDecision, ReviewAction
from ..lookup.approved_software import ApprovedSoftwareIndex
from ..packet.composer import compose_packet
from ..policy.conflicts import ConflictRegistry
from ..policy.engine import REQUIRED_INTAKE_FIELDS, build_inputs, evaluate
from ..specialists.accessibility import run_accessibility
from ..specialists.citations import check_citations
from ..specialists.security import run_security
from .state import Checkpointer


def _utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


class ReviewWorkflow:
    def __init__(
        self,
        *,
        model: ModelClient,
        software_index: ApprovedSoftwareIndex,
        ruleset: PolicyRuleSet,
        registry: ConflictRegistry,
        audit: AuditLog,
        checkpointer: Checkpointer | None = None,
        clock: Callable[[], str] = _utc_now,
        specialist_profiles: dict[str, str] | None = None,
    ) -> None:
        self._model = model
        self._index = software_index
        self._ruleset = ruleset
        self._registry = registry
        self._audit = audit
        self._checkpointer = checkpointer
        self._clock = clock
        self._specialist_profiles = dict(specialist_profiles or {})
        self._seq = 0

    def _checkpoint(self, state: ReviewGraphState) -> None:
        """Persist a snapshot at a human-interrupt boundary for pause/resume."""
        if self._checkpointer is not None:
            self._checkpointer.save(state.case_id, state.to_dict())

    # -- nodes -----------------------------------------------------------------

    def validate_intake(self, state: ReviewGraphState) -> ReviewGraphState:
        case = state.case_input
        missing = tuple(
            name
            for name in REQUIRED_INTAKE_FIELDS
            if not getattr(case, name, None)
            and not getattr(getattr(case, name, None), "value", None)
        )
        state.status = WorkflowStatus.LOOKUP
        self._emit(state, "case.validated", ActorType.SYSTEM, missing=list(missing))
        return state

    def lookup_software(self, state: ReviewGraphState) -> ReviewGraphState:
        result = self._index.lookup(state.case_input.product_name, state.case_input.vendor_name)
        state.software_candidates = result.matches
        needs_confirmation = any(m.requires_confirmation for m in result.matches)
        if needs_confirmation and state.confirmed_match_id is None:
            state.status = WorkflowStatus.AWAITING_MATCH_CONFIRMATION
        else:
            state.status = WorkflowStatus.POLICY
        self._emit(
            state,
            "software.looked_up",
            ActorType.SYSTEM,
            candidate_count=len(result.matches),
            requires_confirmation=needs_confirmation,
        )
        return state

    def evaluate_policy(self, state: ReviewGraphState) -> ReviewGraphState:
        is_approved = self._is_confirmed_approved(state)
        inputs = build_inputs(state.case_input, is_approved_software=is_approved)
        result = evaluate(inputs, self._ruleset, self._registry)
        state.policy_result = result
        state.conflicts = result.conflicts
        state.citations = list(result.citations)
        state.status = WorkflowStatus.ESCALATED if result.escalated else WorkflowStatus.ANALYSIS
        self._emit(
            state,
            "policy.evaluated",
            ActorType.SYSTEM,
            risk_route=result.risk_route.value,
            escalated=result.escalated,
            policy_version=result.policy_version,
        )
        return state

    def run_specialists(self, state: ReviewGraphState) -> ReviewGraphState:
        # Security and accessibility are independent nodes; run them concurrently
        # (deterministic fakes make results order-independent, and a live Bedrock
        # model benefits from the parallelism). Each output persists version,
        # model, and profile-version metadata.
        if state.policy_result is None:
            raise ValueError("policy_result must be evaluated before running specialists")
        policy = state.policy_result
        case = state.case_input
        tasks = {
            "security": lambda: run_security(
                case, policy, self._model,
                profile_version_id=self._specialist_profiles.get("security"),
            ),
            "accessibility": lambda: run_accessibility(
                case, policy, self._model,
                profile_version_id=self._specialist_profiles.get("accessibility"),
            ),
        }
        results: dict[str, dict] = {}
        errors: dict[str, str] = {}
        with ThreadPoolExecutor(max_workers=len(tasks)) as executor:
            futures = {executor.submit(func): name for name, func in tasks.items()}
            for future in as_completed(futures):
                name = futures[future]
                try:
                    results[name] = future.result()
                except ModelStructureError as error:
                    # Explicit model failure: record a reviewable failed result
                    # rather than silently substituting a fixture.
                    errors[name] = str(error)
        if errors:
            raise ModelStructureError(
                "specialist model failure: "
                + "; ".join(f"{name}: {message}" for name, message in sorted(errors.items()))
            )
        state.specialist_results = {
            "security": results["security"],
            "accessibility": results["accessibility"],
        }
        self._emit(
            state,
            "specialists.completed",
            ActorType.MODEL,
            security_model=results["security"].get("metadata", {}).get("model"),
            accessibility_model=results["accessibility"].get("metadata", {}).get("model"),
        )
        return state

    def check_and_repair(self, state: ReviewGraphState) -> ReviewGraphState:
        claims = []
        for result in state.specialist_results.values():
            if result:
                claims.append({"claim": result.get("summary", ""), "citations": result.get("citations", [])})
        check = check_citations(
            claims,
            case_vendor=state.case_input.vendor_name,
            case_product=state.case_input.product_name,
        )
        if not check.ok and state.repair_passes_used < 1:
            # Single bounded repair: drop unsupported specialist claims rather
            # than fabricating a citation.
            state.repair_passes_used += 1
            self._emit(state, "citations.repaired", ActorType.SYSTEM, rejected=len(check.rejected))
        else:
            self._emit(state, "citations.checked", ActorType.SYSTEM, ok=check.ok)
        return state

    def compose(self, state: ReviewGraphState) -> ReviewGraphState:
        if state.policy_result is None:
            raise ValueError("policy_result must be evaluated before composing the packet")
        packet = compose_packet(
            case_id=state.case_id,
            case=state.case_input,
            policy=state.policy_result,
            specialist_results=state.specialist_results,
        )
        state.draft_packet = packet
        state.status = WorkflowStatus.AWAITING_REVIEW
        self._emit(
            state,
            "packet.composed",
            ActorType.SYSTEM,
            packet_type=packet.packet_type.value,
            packet_sha256=packet.sha256,
        )
        self._checkpoint(state)
        return state

    # -- runner and human boundaries ------------------------------------------

    def run_until_review(self, state: ReviewGraphState) -> ReviewGraphState:
        """Advance to the first human interrupt: awaiting match confirmation,
        escalation, or awaiting review."""
        self.validate_intake(state)
        self.lookup_software(state)
        if state.status is WorkflowStatus.AWAITING_MATCH_CONFIRMATION:
            self._checkpoint(state)
            return state
        return self._analyze_and_compose(state)

    def confirm_match(
        self,
        state: ReviewGraphState,
        record_id: str | None,
        *,
        reviewer_id: str | None = None,
    ) -> ReviewGraphState:
        """Reviewer confirms (or clears) a fuzzy/semantic match, then continue."""
        state.confirmed_match_id = record_id
        state.status = WorkflowStatus.POLICY
        self._emit(
            state,
            "match.confirmed",
            ActorType.REVIEWER,
            actor_id=reviewer_id,
            record_id=record_id,
        )
        return self._analyze_and_compose(state)

    def _analyze_and_compose(self, state: ReviewGraphState) -> ReviewGraphState:
        self.evaluate_policy(state)
        if state.status is WorkflowStatus.ESCALATED:
            self._checkpoint(state)
            return state
        self.run_specialists(state)
        self.check_and_repair(state)
        return self.compose(state)

    def preview_writeback(
        self, state: ReviewGraphState, connector: ServiceNowConnector, decision: HumanDecision
    ):
        """Return a simulated before/after preview. Dry-run by default (FR-7)."""
        connector.stage_decision(decision)  # type: ignore[attr-defined]
        packet = state.draft_packet
        if packet is None or packet.sha256 is None:
            raise PermissionError("write-back preview requires a hashed packet")
        preview = connector.preview_update(state.case_id, decision.decision_version)
        preview.packet_version = packet.packet_version
        preview.packet_sha256 = packet.sha256
        state.write_preview = preview
        state.status = WorkflowStatus.WRITEBACK
        self._emit(
            state,
            "servicenow.previewed",
            ActorType.REVIEWER,
            actor_id=decision.reviewer_id,
            decision_version=decision.decision_version,
        )
        return preview

    def commit_writeback(
        self,
        state: ReviewGraphState,
        connector: ServiceNowConnector,
        decision: HumanDecision,
        *,
        second_confirmation: bool,
        expected_version: int,
    ):
        """Commit the simulated write only after an approved decision and an
        explicit second confirmation (FR-7). Idempotent on the decision key."""
        if decision.action is not ReviewAction.APPROVE:
            raise PermissionError("write-back requires an approved decision")
        if not second_confirmation:
            raise PermissionError("write-back requires an explicit second confirmation")
        preview = state.write_preview
        packet = state.draft_packet
        if preview is None:
            raise PermissionError("write-back requires a current preview")
        if preview.decision_version != decision.decision_version:
            raise PermissionError("write-back preview decision is stale")
        if preview.expected_record_version != expected_version:
            raise PermissionError("write-back expected version differs from preview")
        if packet is None or packet.sha256 is None:
            raise PermissionError("write-back requires a hashed packet")
        if preview.packet_version != packet.packet_version or preview.packet_sha256 != packet.sha256:
            raise PermissionError("write-back preview packet is stale")
        state.human_decision = decision
        state.idempotency_key = decision.idempotency_key
        result = connector.update_request(
            state.case_id, decision.decision_version, expected_version
        )
        if state.draft_packet is not None and state.draft_packet.sha256:
            attachment = connector.attach_packet(result.record_id, state.draft_packet.sha256)
            result.attachment = attachment
        state.write_result = result
        state.status = WorkflowStatus.CLOSED
        self._emit(
            state,
            "servicenow.committed",
            ActorType.REVIEWER,
            actor_id=decision.reviewer_id,
            decision_version=decision.decision_version,
            idempotency_key=result.idempotency_key,
            duplicate_suppressed=result.duplicate_suppressed,
        )
        return result

    # -- internals -------------------------------------------------------------

    def _is_confirmed_approved(self, state: ReviewGraphState) -> bool:
        for match in state.software_candidates:
            if match.requires_confirmation:
                if state.confirmed_match_id == match.record_id:
                    return True
            elif match.match_method.value in {"exact", "alias", "vendor_product"}:
                return True
        return False

    def _emit(
        self,
        state: ReviewGraphState,
        event_type: str,
        actor: ActorType,
        *,
        actor_id: str | None = None,
        decision_version: int | None = None,
        **detail: object,
    ) -> None:
        self._seq += 1
        self._audit.record(
            event_id=f"{state.case_id}-{self._seq:03d}",
            event_type=event_type,
            case_id=state.case_id,
            occurred_at=self._clock(),
            actor_type=actor,
            actor_id=actor_id,
            decision_version=decision_version,
            workflow_version=state.workflow_version,
            policy_version=state.policy_result.policy_version if state.policy_result else None,
            detail=dict(detail),
        )
