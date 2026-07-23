"""The sign-off chain.

A gate decision is an input to a signature, not a substitute for one. This
module records who is required to sign for a phase, who actually has, and
whether the resulting record would survive being questioned.

Two constraints are enforced rather than assumed:

**Independence.** The party who executed a test cannot be the sole party who
witnesses it, and the party who witnessed cannot be the sole party who
approves the phase. Self-witnessed evidence is not evidence; it is a claim.

**Currency.** An approval given before the last piece of evidence changed is
stale. Approving on Monday and failing a test on Wednesday does not leave you
with an approved phase, and a record that says otherwise is worse than no
record at all.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from .types import Phase

__all__ = [
    "Role",
    "Signatory",
    "Approval",
    "SignoffPolicy",
    "SignoffStatus",
    "check_signoff",
]


class Role(StrEnum):
    TEST_ENGINEER = "test_engineer"  # executes
    TEST_WITNESS = "test_witness"  # observes execution
    TEST_MANAGER = "test_manager"  # owns the evidence
    QUALITY = "quality"  # owns the process
    CUSTOMER = "customer"  # accepts


@dataclass(frozen=True, slots=True)
class Signatory:
    party: str
    role: Role
    organisation: str


@dataclass(frozen=True, slots=True)
class Approval:
    signatory: Signatory
    phase: Phase
    signed_at: datetime
    qualified: bool = False  # signed subject to stated conditions
    note: str = ""

    def __post_init__(self) -> None:
        if self.signed_at.tzinfo is None:
            raise ValueError("signed_at must be timezone-aware")


@dataclass(frozen=True, slots=True)
class SignoffPolicy:
    """Who must sign, per phase."""

    required: dict[Phase, frozenset[Role]] = field(
        default_factory=lambda: {
            Phase.FACTORY: frozenset({Role.TEST_MANAGER, Role.QUALITY}),
            Phase.SITE: frozenset({Role.TEST_MANAGER, Role.QUALITY}),
            Phase.INTEGRATION: frozenset(
                {Role.TEST_MANAGER, Role.QUALITY, Role.CUSTOMER}
            ),
            Phase.END_TO_END: frozenset(
                {Role.TEST_MANAGER, Role.QUALITY, Role.CUSTOMER}
            ),
        }
    )
    require_independence: bool = True
    require_currency: bool = True


@dataclass(frozen=True, slots=True)
class SignoffStatus:
    phase: Phase
    satisfied: bool
    missing_roles: tuple[Role, ...]
    stale_approvals: tuple[str, ...]
    independence_breaches: tuple[str, ...]
    qualified_approvals: tuple[str, ...]
    signed_by: tuple[str, ...]

    def explain(self) -> str:
        lines = [
            f"Sign-off — {self.phase.value}: "
            f"{'COMPLETE' if self.satisfied else 'INCOMPLETE'}"
        ]
        if self.signed_by:
            lines.append(f"  signed: {', '.join(self.signed_by)}")
        if self.missing_roles:
            lines.append(f"  missing: {', '.join(r.value for r in self.missing_roles)}")
        for ref in self.stale_approvals:
            lines.append(f"  stale:  {ref} signed before evidence last changed")
        for ref in self.independence_breaches:
            lines.append(f"  independence: {ref}")
        for ref in self.qualified_approvals:
            lines.append(f"  qualified: {ref} signed subject to conditions")
        return "\n".join(lines)


def check_signoff(
    approvals: tuple[Approval, ...],
    *,
    phase: Phase,
    evidence_last_changed: datetime,
    policy: SignoffPolicy | None = None,
) -> SignoffStatus:
    """Check whether the sign-off record for a phase is complete and current."""
    if evidence_last_changed.tzinfo is None:
        raise ValueError("evidence_last_changed must be timezone-aware")
    policy = policy or SignoffPolicy()

    scoped = tuple(a for a in approvals if a.phase is phase)
    required = policy.required.get(phase, frozenset())
    present = {a.signatory.role for a in scoped}
    missing = tuple(sorted(required - present, key=lambda r: r.value))

    stale: list[str] = []
    if policy.require_currency:
        stale = [
            f"{a.signatory.party} ({a.signatory.role.value})"
            for a in scoped
            if a.signed_at < evidence_last_changed
        ]

    breaches: list[str] = []
    if policy.require_independence:
        by_party: dict[str, set[Role]] = {}
        for a in scoped:
            by_party.setdefault(a.signatory.party, set()).add(a.signatory.role)
        for party, roles in by_party.items():
            if len(roles & required) > 1:
                held = ", ".join(sorted(r.value for r in roles & required))
                breaches.append(f"{party} holds {held} for the same phase")
        customer_orgs = {
            a.signatory.organisation
            for a in scoped
            if a.signatory.role is Role.CUSTOMER
        }
        supplier_orgs = {
            a.signatory.organisation
            for a in scoped
            if a.signatory.role in {Role.TEST_MANAGER, Role.TEST_ENGINEER}
        }
        overlap = customer_orgs & supplier_orgs
        if overlap:
            breaches.append(
                f"customer and supplier roles held within the same organisation: "
                f"{', '.join(sorted(overlap))}"
            )

    qualified = tuple(
        f"{a.signatory.party}: {a.note}" if a.note else a.signatory.party
        for a in scoped
        if a.qualified
    )

    satisfied = not missing and not stale and not breaches

    return SignoffStatus(
        phase=phase,
        satisfied=satisfied,
        missing_roles=missing,
        stale_approvals=tuple(stale),
        independence_breaches=tuple(breaches),
        qualified_approvals=qualified,
        signed_by=tuple(
            sorted(f"{a.signatory.party} ({a.signatory.role.value})" for a in scoped)
        ),
    )
