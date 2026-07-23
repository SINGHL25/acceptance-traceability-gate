"""The evidence pack.

The artefact that outlives the programme. Eighteen months after handover,
somebody asks why a phase was accepted with three defects open. The answer
has to be a document that states what was known **at the time**, what rule was
applied, and who signed — not a reconstruction from memory and a spreadsheet
that has been edited since.

So the pack is generated from the evidence, is deterministic for a given
input, and states its own thresholds inline. It is deliberately plain
Markdown: it needs to be readable in fifteen years by someone with no
toolchain.
"""

from __future__ import annotations

from datetime import datetime

from .defects import AgeingPolicy, DefectSummary, age_defects
from .gate import GateRule
from .phases import ChainResult
from .signoff import SignoffStatus
from .traceability import Matrix
from .types import Evidence

__all__ = ["build_pack"]


def _pct(x: float) -> str:
    return f"{x:.1%}"


def _table(headers: list[str], rows: list[list[str]]) -> str:
    if not rows:
        return "_None._\n"
    out = ["| " + " | ".join(headers) + " |"]
    out.append("|" + "|".join("---" for _ in headers) + "|")
    for r in rows:
        out.append("| " + " | ".join(r) + " |")
    return "\n".join(out) + "\n"


def build_pack(
    evidence: Evidence,
    matrix: Matrix,
    chain: ChainResult,
    *,
    at: datetime,
    rule: GateRule | None = None,
    ageing: AgeingPolicy | None = None,
    signoffs: tuple[SignoffStatus, ...] = (),
    programme: str = "Synthetic programme",
) -> str:
    """Render a complete, self-describing acceptance record as Markdown."""
    if at.tzinfo is None:
        raise ValueError("`at` must be timezone-aware")
    rule = rule or GateRule()
    ageing = ageing or AgeingPolicy()
    summary: DefectSummary = age_defects(evidence.defects, at=at, policy=ageing)

    p: list[str] = []
    a = p.append

    a(f"# Acceptance evidence pack — {programme}\n")
    a(f"**Generated:** {at.isoformat()}  ")
    a(f"**Requirements:** {len(evidence.requirements)}  ")
    a(f"**Test cases:** {len(evidence.tests)}  ")
    a(f"**Executions:** {len(evidence.executions)}  ")
    a(f"**Open defects:** {len(summary.aged)}\n")
    a(
        "> This pack is generated from evidence and is deterministic for a "
        "given input. It states the rule applied at the time of the decision, "
        "inline, so the decision can be assessed later without reconstructing "
        "the configuration.\n"
    )

    a("## 1. Rule applied\n")
    a(
        _table(
            ["Parameter", "Value"],
            [
                ["Minimum trace coverage", _pct(rule.min_trace_coverage)],
                ["Minimum verified fraction", _pct(rule.min_verified_fraction)],
                ["Blocking severity", rule.blocking_severity.name],
                [
                    "MAJOR conceded with workaround",
                    "yes" if rule.allow_major_with_workaround else "no",
                ],
                [
                    "Safety exempt from thresholds",
                    "yes" if rule.safety_requires_full_verification else "no",
                ],
            ],
        )
    )
    a(
        "Ageing targets (days to closure): "
        + ", ".join(f"{s.name} {d}" for s, d in sorted(ageing.targets.items()))
        + f"; escalate at {ageing.escalate_multiple:g}x, "
        f"breach at {ageing.breach_multiple:g}x.\n"
    )

    a("## 2. Phase chain\n")
    a(
        _table(
            ["Phase", "Status", "Trace", "Verified", "Blocking", "Entitled to start"],
            [
                [
                    s.phase.value,
                    s.status,
                    _pct(s.decision.trace_coverage),
                    _pct(s.decision.verified_fraction),
                    str(len(s.decision.blocking_reasons)),
                    "yes" if s.entry_met else f"no — {s.predecessor.value} not cleared",
                ]
                for s in chain.states
            ],
        )
    )
    blocking = chain.blocking_phase
    a(
        f"**Earliest phase not cleared:** `{blocking.value}`. "
        "This is where the remedial work belongs; downstream failures are "
        "expected to persist until it clears.\n"
        if blocking
        else "**All phases cleared.**\n"
    )

    a("## 3. Traceability\n")
    a(
        _table(
            ["Metric", "Value", "Meaning"],
            [
                [
                    "Trace coverage",
                    _pct(matrix.trace_coverage),
                    "Verifiable requirements with at least one covering test — "
                    "the *plan*",
                ],
                [
                    "Verified fraction",
                    _pct(matrix.verified_fraction),
                    "Verifiable requirements where every covering test passed — "
                    "the *evidence*",
                ],
                [
                    "Orphan requirements",
                    str(len(matrix.orphan_requirements)),
                    "No test agreed to verify these",
                ],
                [
                    "Orphan tests",
                    str(len(matrix.orphan_tests)),
                    "Effort spent verifying nothing traceable",
                ],
            ],
        )
    )
    orphans = matrix.orphan_requirements
    if orphans:
        a("**Requirements with no covering test:**\n")
        a("```\n" + ", ".join(s.requirement.ref for s in orphans) + "\n```\n")

    a("## 4. Defect position\n")
    counts = summary.counts()
    a(
        _table(
            ["Tier", "Count", "Meaning"],
            [
                ["working", str(counts["working"]), "Inside target, with the team"],
                ["overdue", str(counts["overdue"]), "Past target, test manager"],
                [
                    "escalated",
                    str(counts["escalated"]),
                    f"Past {ageing.escalate_multiple:g}x target, programme manager",
                ],
                [
                    "breached",
                    str(counts["breached"]),
                    f"Past {ageing.breach_multiple:g}x target, customer notified",
                ],
            ],
        )
    )
    if summary.aged:
        a("**Oldest open defects:**\n")
        a(
            _table(
                ["Ref", "Severity", "Against", "Age (days)", "x target", "Tier"],
                [
                    [
                        d.defect.ref,
                        d.defect.severity.name,
                        d.defect.against,
                        f"{d.age_days:.0f}",
                        f"{d.ratio:.1f}",
                        d.tier.value,
                    ]
                    for d in summary.aged[:10]
                ],
            )
        )

    a("## 5. Sign-off\n")
    if not signoffs:
        a("_No sign-off record supplied._\n")
    for s in signoffs:
        a(f"### {s.phase.value} — {'COMPLETE' if s.satisfied else 'INCOMPLETE'}\n")
        if s.signed_by:
            a("Signed by: " + ", ".join(s.signed_by) + "\n")
        if s.missing_roles:
            a("Missing: " + ", ".join(r.value for r in s.missing_roles) + "\n")
        for ref in s.stale_approvals:
            a(f"- Stale — {ref} signed before the evidence last changed\n")
        for ref in s.independence_breaches:
            a(f"- Independence — {ref}\n")
        for ref in s.qualified_approvals:
            a(f"- Qualified — {ref}\n")

    a("## 6. Limitations of this pack\n")
    a(
        "- The gate **recommends**; it does not sign. Acceptance is a human "
        "decision recorded in section 5.\n"
        "- Coverage figures describe requirements marked verifiable. "
        "Unverifiable requirements are excluded from both numerator and "
        "denominator and must be closed by other means.\n"
        "- A passing test is evidence about the case it exercised, not about "
        "the requirement in general.\n"
        "- Defect ageing is measured against targets in section 1. Changing "
        "those targets changes the tiers and invalidates comparison with "
        "earlier packs.\n"
    )

    return "\n".join(p)
