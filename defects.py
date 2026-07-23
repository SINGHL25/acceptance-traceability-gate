"""Defect ageing and escalation.

Severity alone is a static picture. A CRITICAL raised this morning and a
CRITICAL open for eleven weeks are the same row in most defect reports, and
they are not remotely the same problem: the first is being worked, the second
is being tolerated.

Escalation here is a function of **severity and age together**, with the
target response time set per severity as a signed parameter. The output is
advisory — it names who should be told, not what they should decide.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum

from .types import Defect, Severity

__all__ = ["Tier", "AgeingPolicy", "AgedDefect", "age_defects", "DefectSummary"]


class Tier(StrEnum):
    """Who is expected to be aware. Not who decides."""

    WORKING = "working"  # inside target, engineering team
    OVERDUE = "overdue"  # past target, test manager
    ESCALATED = "escalated"  # 2x target, programme manager
    BREACHED = "breached"  # 4x target, customer notification


@dataclass(frozen=True, slots=True)
class AgeingPolicy:
    """Target days to closure per severity.

    These are commitments, not estimates. They belong in a reviewed
    configuration next to the gate thresholds, for the same reason.
    """

    targets: dict[Severity, int] = field(
        default_factory=lambda: {
            Severity.CRITICAL: 2,
            Severity.MAJOR: 10,
            Severity.MINOR: 30,
            Severity.TRIVIAL: 90,
        }
    )
    escalate_multiple: float = 2.0
    breach_multiple: float = 4.0

    def __post_init__(self) -> None:
        if not 1.0 < self.escalate_multiple < self.breach_multiple:
            raise ValueError(
                "multiples must satisfy 1 < escalate < breach; "
                f"got {self.escalate_multiple} and {self.breach_multiple}"
            )
        missing = set(Severity) - set(self.targets)
        if missing:
            raise ValueError(f"no ageing target for {sorted(s.name for s in missing)}")

    def target_for(self, severity: Severity) -> timedelta:
        return timedelta(days=self.targets[severity])


@dataclass(frozen=True, slots=True)
class AgedDefect:
    """A defect with its age and escalation tier resolved at a point in time."""

    defect: Defect
    age: timedelta
    target: timedelta
    tier: Tier

    @property
    def age_days(self) -> float:
        return self.age.total_seconds() / 86_400

    @property
    def overdue_by(self) -> timedelta:
        return max(self.age - self.target, timedelta(0))

    @property
    def ratio(self) -> float:
        """Age as a multiple of target. 1.0 means exactly on the commitment."""
        return self.age / self.target if self.target else 0.0


def _tier(age: timedelta, target: timedelta, policy: AgeingPolicy) -> Tier:
    if age <= target:
        return Tier.WORKING
    if age <= target * policy.breach_multiple:
        return (
            Tier.ESCALATED if age > target * policy.escalate_multiple else Tier.OVERDUE
        )
    return Tier.BREACHED


@dataclass(frozen=True, slots=True)
class DefectSummary:
    """Rolled-up defect position for a report or an evidence pack."""

    aged: tuple[AgedDefect, ...]
    as_at: datetime

    def by_tier(self, tier: Tier) -> tuple[AgedDefect, ...]:
        return tuple(a for a in self.aged if a.tier is tier)

    def by_severity(self, severity: Severity) -> tuple[AgedDefect, ...]:
        return tuple(a for a in self.aged if a.defect.severity is severity)

    @property
    def oldest(self) -> AgedDefect | None:
        return max(self.aged, key=lambda a: a.age, default=None)

    @property
    def worst_tier(self) -> Tier:
        for tier in (Tier.BREACHED, Tier.ESCALATED, Tier.OVERDUE):
            if self.by_tier(tier):
                return tier
        return Tier.WORKING

    def counts(self) -> dict[str, int]:
        return {t.value: len(self.by_tier(t)) for t in Tier}

    def explain(self) -> str:
        if not self.aged:
            return "No open defects."
        lines = [f"Open defects: {len(self.aged)}"]
        for tier in Tier:
            items = self.by_tier(tier)
            if items:
                refs = ", ".join(a.defect.ref for a in items[:8])
                more = f" (+{len(items) - 8})" if len(items) > 8 else ""
                lines.append(f"  {tier.value:<10} {len(items):>3}  {refs}{more}")
        oldest = self.oldest
        if oldest:
            lines.append(
                f"  oldest: {oldest.defect.ref} "
                f"({oldest.defect.severity.name}, {oldest.age_days:.0f}d, "
                f"{oldest.ratio:.1f}x target)"
            )
        return "\n".join(lines)


def age_defects(
    defects: tuple[Defect, ...],
    *,
    at: datetime,
    policy: AgeingPolicy | None = None,
) -> DefectSummary:
    """Age every open defect and assign an escalation tier.

    Closed defects are excluded: their age is a historical metric, not a call
    to action, and mixing them in is how a defect report starts describing the
    past instead of the present.
    """
    if at.tzinfo is None:
        raise ValueError("`at` must be timezone-aware")
    policy = policy or AgeingPolicy()

    aged: list[AgedDefect] = []
    for d in defects:
        if not d.is_open:
            continue
        if d.raised_at > at:
            raise ValueError(f"defect {d.ref} raised in the future relative to `at`")
        age = at - d.raised_at
        target = policy.target_for(d.severity)
        aged.append(
            AgedDefect(
                defect=d, age=age, target=target, tier=_tier(age, target, policy)
            )
        )

    aged.sort(key=lambda a: (-a.ratio, a.defect.severity))
    return DefectSummary(aged=tuple(aged), as_at=at)
