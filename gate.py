"""The acceptance gate.

Design rule, stated up front: **the gate recommends, it does not sign.**

It returns a graded outcome with every contributing reason attached, because
the decision it informs is contractual and someone will be asked to justify
it months later. A boolean cannot be justified. A boolean also cannot express
the most common real state of a programme approaching a milestone, which is
neither "ready" nor "not ready" but "ready except for these four things, and
here is who has to decide about them".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from .traceability import Matrix
from .types import Defect, Phase, Severity

__all__ = ["Outcome", "Finding", "GateRule", "Decision", "evaluate"]


class Outcome(StrEnum):
    ACCEPT = "accept"
    ACCEPT_WITH_CONDITIONS = "accept_with_conditions"
    WITHHOLD = "withhold"


class Finding(StrEnum):
    ORPHAN_REQUIREMENT = "orphan_requirement"
    ORPHAN_TEST = "orphan_test"
    TRACE_COVERAGE_BELOW_THRESHOLD = "trace_coverage_below_threshold"
    VERIFIED_BELOW_THRESHOLD = "verified_below_threshold"
    BLOCKING_DEFECT_OPEN = "blocking_defect_open"
    SAFETY_REQUIREMENT_UNVERIFIED = "safety_requirement_unverified"
    EXECUTION_INCOMPLETE = "execution_incomplete"


@dataclass(frozen=True, slots=True)
class Reason:
    finding: Finding
    detail: str
    blocking: bool
    refs: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class GateRule:
    """Thresholds, named and versioned.

    These are parameters, not constants buried in a comparison. When a
    programme argues about whether 92% was good enough, the argument should be
    about this number in a reviewed configuration, not about someone's code.
    """

    min_trace_coverage: float = 1.0
    min_verified_fraction: float = 0.95
    blocking_severity: Severity = Severity.MAJOR
    allow_major_with_workaround: bool = False
    safety_requires_full_verification: bool = True

    def __post_init__(self) -> None:
        for name in ("min_trace_coverage", "min_verified_fraction"):
            v = getattr(self, name)
            if not 0.0 <= v <= 1.0:
                raise ValueError(f"{name} must be within [0, 1], got {v}")


@dataclass(frozen=True, slots=True)
class Decision:
    outcome: Outcome
    phase: Phase
    reasons: tuple[Reason, ...]
    trace_coverage: float
    verified_fraction: float
    decided_at: datetime
    rule: GateRule = field(default_factory=GateRule)

    @property
    def blocking_reasons(self) -> tuple[Reason, ...]:
        return tuple(r for r in self.reasons if r.blocking)

    @property
    def conditions(self) -> tuple[Reason, ...]:
        return tuple(r for r in self.reasons if not r.blocking)

    def explain(self) -> str:
        lines = [
            f"{self.outcome.value.upper()} — {self.phase.value} phase",
            f"  trace coverage : {self.trace_coverage:6.1%}",
            f"  verified       : {self.verified_fraction:6.1%}",
        ]
        if not self.reasons:
            lines.append("  no findings")
        for r in self.reasons:
            marker = "BLOCK" if r.blocking else "cond "
            lines.append(f"  [{marker}] {r.detail}")
        return "\n".join(lines)


def _blocks(defect: Defect, rule: GateRule) -> bool:
    if not defect.is_open:
        return False
    if defect.severity > rule.blocking_severity:
        return False
    conceded = (
        defect.severity is Severity.MAJOR
        and defect.workaround
        and rule.allow_major_with_workaround
    )
    return not conceded


def evaluate(
    matrix: Matrix,
    defects: tuple[Defect, ...],
    *,
    phase: Phase,
    rule: GateRule | None = None,
    at: datetime,
) -> Decision:
    """Evaluate the gate for one phase and return a graded decision."""
    if at.tzinfo is None:
        raise ValueError("`at` must be timezone-aware")
    rule = rule or GateRule()

    scoped = [s for s in matrix.for_phase(phase) if s.requirement.verifiable]
    pool = len(scoped) or 1
    traced = sum(1 for s in scoped if not s.is_orphan) / pool
    verified = sum(1 for s in scoped if s.is_verified) / pool

    reasons: list[Reason] = []

    orphans = tuple(s.requirement.ref for s in scoped if s.is_orphan)
    if orphans:
        reasons.append(
            Reason(
                Finding.ORPHAN_REQUIREMENT,
                f"{len(orphans)} requirement(s) have no covering test",
                blocking=traced < rule.min_trace_coverage,
                refs=orphans,
            )
        )

    if traced < rule.min_trace_coverage:
        reasons.append(
            Reason(
                Finding.TRACE_COVERAGE_BELOW_THRESHOLD,
                f"trace coverage {traced:.1%} below required "
                f"{rule.min_trace_coverage:.1%}",
                blocking=True,
            )
        )

    if verified < rule.min_verified_fraction:
        reasons.append(
            Reason(
                Finding.VERIFIED_BELOW_THRESHOLD,
                f"verified {verified:.1%} below required "
                f"{rule.min_verified_fraction:.1%}",
                blocking=True,
            )
        )

    indeterminate = tuple(s.requirement.ref for s in scoped if s.is_indeterminate)
    if indeterminate:
        reasons.append(
            Reason(
                Finding.EXECUTION_INCOMPLETE,
                f"{len(indeterminate)} requirement(s) have tests neither passed "
                "nor failed (blocked or not run)",
                blocking=False,
                refs=indeterminate,
            )
        )

    if rule.safety_requires_full_verification:
        unsafe = tuple(
            s.requirement.ref
            for s in scoped
            if s.requirement.safety_related and not s.is_verified
        )
        if unsafe:
            reasons.append(
                Reason(
                    Finding.SAFETY_REQUIREMENT_UNVERIFIED,
                    f"{len(unsafe)} safety-related requirement(s) not fully "
                    "verified — no threshold applies to these",
                    blocking=True,
                    refs=unsafe,
                )
            )

    in_scope = {s.requirement.ref for s in scoped}
    blocking_defects = tuple(
        d.ref for d in defects if d.against in in_scope and _blocks(d, rule)
    )
    if blocking_defects:
        reasons.append(
            Reason(
                Finding.BLOCKING_DEFECT_OPEN,
                f"{len(blocking_defects)} open defect(s) at or above "
                f"{rule.blocking_severity.name}",
                blocking=True,
                refs=blocking_defects,
            )
        )

    conceded = tuple(
        d.ref
        for d in defects
        if d.against in in_scope and d.is_open and not _blocks(d, rule)
    )
    if conceded:
        reasons.append(
            Reason(
                Finding.BLOCKING_DEFECT_OPEN,
                f"{len(conceded)} open defect(s) carried as conditions",
                blocking=False,
                refs=conceded,
            )
        )

    if matrix.orphan_tests:
        reasons.append(
            Reason(
                Finding.ORPHAN_TEST,
                f"{len(matrix.orphan_tests)} test(s) trace to no requirement",
                blocking=False,
                refs=matrix.orphan_tests,
            )
        )

    if any(r.blocking for r in reasons):
        outcome = Outcome.WITHHOLD
    elif reasons:
        outcome = Outcome.ACCEPT_WITH_CONDITIONS
    else:
        outcome = Outcome.ACCEPT

    return Decision(
        outcome=outcome,
        phase=phase,
        reasons=tuple(reasons),
        trace_coverage=traced,
        verified_fraction=verified,
        decided_at=at,
        rule=rule,
    )
