"""The phase chain.

A phase gate is not just "did this phase pass". It is also "was this phase
entitled to start". Running end-to-end testing while site acceptance is still
withheld is how programmes generate expensive evidence about a configuration
that is about to change underneath them.

So each phase carries **entry criteria** as well as exit criteria, and the
chain refuses to report a downstream phase as accepted when an upstream one
is not. The refusal is reported as a distinct finding rather than folded into
the phase's own result, because the two have different owners and different
remedies.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .gate import Decision, GateRule, Outcome, evaluate
from .traceability import Matrix
from .types import Defect, Phase

__all__ = ["PHASE_ORDER", "PhaseState", "ChainResult", "evaluate_chain"]

#: Canonical order. Each phase may only start once its predecessor has cleared.
PHASE_ORDER: tuple[Phase, ...] = (
    Phase.FACTORY,
    Phase.SITE,
    Phase.INTEGRATION,
    Phase.END_TO_END,
)

#: What each phase is entitled to assume, stated in plain language so it can
#: be read by someone who will never open the code.
ENTRY_CRITERIA: dict[Phase, str] = {
    Phase.FACTORY: "Design baseline frozen; test environment configured.",
    Phase.SITE: "Factory acceptance cleared; hardware installed and powered.",
    Phase.INTEGRATION: "Site acceptance cleared; upstream and downstream "
    "interfaces available in their production configuration.",
    Phase.END_TO_END: "Integration acceptance cleared; full transaction chain "
    "under production configuration and production-representative load.",
}


@dataclass(frozen=True, slots=True)
class PhaseState:
    """One phase's own result plus whether it was entitled to run."""

    phase: Phase
    decision: Decision
    entry_met: bool
    entry_criteria: str
    predecessor: Phase | None

    @property
    def cleared(self) -> bool:
        """Cleared means the phase passed *and* was entitled to start."""
        return self.entry_met and self.decision.outcome is not Outcome.WITHHOLD

    @property
    def status(self) -> str:
        if not self.entry_met:
            return "NOT ENTITLED TO START"
        return self.decision.outcome.value.replace("_", " ").upper()


@dataclass(frozen=True, slots=True)
class ChainResult:
    """The whole programme, phase by phase, in order."""

    states: tuple[PhaseState, ...]
    evaluated_at: datetime

    @property
    def furthest_cleared(self) -> Phase | None:
        cleared = [s.phase for s in self.states if s.cleared]
        return cleared[-1] if cleared else None

    @property
    def blocking_phase(self) -> Phase | None:
        """The earliest phase that has not cleared. This is where the work is.

        Reporting the *latest* failing phase is a common and misleading habit:
        it points the programme at symptoms rather than at the upstream cause.
        """
        for s in self.states:
            if not s.cleared:
                return s.phase
        return None

    def state_for(self, phase: Phase) -> PhaseState:
        return next(s for s in self.states if s.phase is phase)

    def explain(self) -> str:
        lines = ["Acceptance chain", "=" * 52]
        for s in self.states:
            lines.append(f"{s.phase.value:<14} {s.status}")
            lines.append(f"{'':<14} entry: {s.entry_criteria}")
            if not s.entry_met:
                lines.append(
                    f"{'':<14} blocked by upstream phase: {s.predecessor.value}"
                )
            else:
                lines.append(
                    f"{'':<14} traced {s.decision.trace_coverage:.1%} · "
                    f"verified {s.decision.verified_fraction:.1%} · "
                    f"{len(s.decision.blocking_reasons)} blocking"
                )
            lines.append("")
        blocking = self.blocking_phase
        lines.append(
            f"Earliest phase not cleared: {blocking.value}"
            if blocking
            else "All phases cleared."
        )
        return "\n".join(lines)


def evaluate_chain(
    matrix: Matrix,
    defects: tuple[Defect, ...],
    *,
    rule: GateRule | None = None,
    at: datetime,
    order: tuple[Phase, ...] = PHASE_ORDER,
) -> ChainResult:
    """Evaluate every phase in order, propagating entry entitlement forward."""
    if at.tzinfo is None:
        raise ValueError("`at` must be timezone-aware")

    states: list[PhaseState] = []
    upstream_cleared = True
    predecessor: Phase | None = None

    for phase in order:
        decision = evaluate(matrix, defects, phase=phase, rule=rule, at=at)
        state = PhaseState(
            phase=phase,
            decision=decision,
            entry_met=upstream_cleared,
            entry_criteria=ENTRY_CRITERIA[phase],
            predecessor=predecessor,
        )
        states.append(state)
        upstream_cleared = state.cleared
        predecessor = phase

    return ChainResult(states=tuple(states), evaluated_at=at)
