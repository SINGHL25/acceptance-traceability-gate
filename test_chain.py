"""Domain claims about phase entitlement, ageing, sign-off and the record."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from acceptance_gate import (
    AgeingPolicy,
    Approval,
    Defect,
    Evidence,
    Execution,
    Phase,
    Requirement,
    Role,
    Severity,
    Signatory,
    SignoffPolicy,
    TestCase,
    Tier,
    Verdict,
    age_defects,
    build_matrix,
    build_pack,
    check_signoff,
    evaluate_chain,
)

NOW = datetime(2026, 3, 1, 9, 0, tzinfo=UTC)


def programme(*, site_ok: bool = True) -> Evidence:
    """Two phases: site and end-to-end, each with one requirement."""
    reqs = (
        Requirement("REQ-001", "site obligation", Phase.SITE),
        Requirement("REQ-002", "e2e obligation", Phase.END_TO_END),
    )
    tests = (
        TestCase("TC-001", "verify site", Phase.SITE, frozenset({"REQ-001"})),
        TestCase("TC-002", "verify e2e", Phase.END_TO_END, frozenset({"REQ-002"})),
    )
    execs = (
        Execution("TC-001", Verdict.PASS if site_ok else Verdict.FAIL, NOW),
        Execution("TC-002", Verdict.PASS, NOW),
    )
    return Evidence(reqs, tests, execs)


def chain_for(ev: Evidence):
    return evaluate_chain(build_matrix(ev, at=NOW), ev.defects, at=NOW)


# --- phase chain -----------------------------------------------------------


def test_a_phase_cannot_clear_while_an_upstream_phase_is_withheld():
    """End-to-end evidence gathered on a configuration that is about to change
    is expensive and worthless. Entitlement to start is part of the gate."""
    chain = chain_for(programme(site_ok=False))
    e2e = chain.state_for(Phase.END_TO_END)
    assert e2e.decision.outcome.value != "withhold"  # its own tests passed
    assert not e2e.entry_met  # but it was never entitled to run
    assert not e2e.cleared
    assert e2e.status == "NOT ENTITLED TO START"


def test_entry_failure_is_reported_separately_from_the_phase_result():
    """The two have different owners and different remedies, so folding them
    together sends the wrong team to fix it.

    Note the propagation: end-to-end is blocked by *integration*, its immediate
    predecessor, not by the site failure that actually caused the stall. The
    chain reports the local blocker per phase and the root cause once, via
    ``blocking_phase``. Conflating those two is how a status report ends up
    telling four different teams they are the problem.
    """
    chain = chain_for(programme(site_ok=False))
    e2e = chain.state_for(Phase.END_TO_END)
    assert e2e.predecessor is Phase.INTEGRATION
    assert not e2e.entry_met
    assert "blocked by upstream phase: integration" in chain.explain()


def test_the_chain_reports_the_earliest_failure_not_the_latest():
    """Pointing at the last failing phase points the programme at symptoms."""
    chain = chain_for(programme(site_ok=False))
    assert chain.blocking_phase is Phase.FACTORY  # no factory evidence at all
    assert chain.furthest_cleared is None


def test_a_clean_programme_clears_every_phase_in_order():
    ev = Evidence(
        requirements=tuple(
            Requirement(f"REQ-{i}", "o", p)
            for i, p in enumerate(
                (Phase.FACTORY, Phase.SITE, Phase.INTEGRATION, Phase.END_TO_END)
            )
        ),
        tests=tuple(
            TestCase(f"TC-{i}", "t", p, frozenset({f"REQ-{i}"}))
            for i, p in enumerate(
                (Phase.FACTORY, Phase.SITE, Phase.INTEGRATION, Phase.END_TO_END)
            )
        ),
        executions=tuple(Execution(f"TC-{i}", Verdict.PASS, NOW) for i in range(4)),
    )
    chain = chain_for(ev)
    assert chain.blocking_phase is None
    assert chain.furthest_cleared is Phase.END_TO_END


# --- defect ageing ---------------------------------------------------------


def test_two_defects_of_equal_severity_are_not_equal_problems():
    """One raised this morning is being worked. One open eleven weeks is being
    tolerated. Most defect reports show them as the same row."""
    fresh = Defect("D-NEW", Severity.CRITICAL, NOW - timedelta(hours=6), against="R1")
    stale = Defect("D-OLD", Severity.CRITICAL, NOW - timedelta(days=77), against="R1")
    summary = age_defects((fresh, stale), at=NOW)
    tiers = {a.defect.ref: a.tier for a in summary.aged}
    assert tiers["D-NEW"] is Tier.WORKING
    assert tiers["D-OLD"] is Tier.BREACHED
    assert summary.worst_tier is Tier.BREACHED


def test_ageing_is_measured_against_severity_specific_targets():
    """Thirty days is a breach for a CRITICAL and inside target for a MINOR."""
    at_30d = NOW - timedelta(days=30)
    crit = Defect("D-C", Severity.CRITICAL, at_30d, against="R1")
    minor = Defect("D-M", Severity.MINOR, at_30d, against="R1")
    tiers = {a.defect.ref: a.tier for a in age_defects((crit, minor), at=NOW).aged}
    assert tiers["D-C"] is Tier.BREACHED
    assert tiers["D-M"] is Tier.WORKING


def test_closed_defects_are_excluded_from_the_ageing_position():
    """A defect report that includes closed items describes the past."""
    closed = Defect(
        "D1",
        Severity.CRITICAL,
        NOW - timedelta(days=90),
        against="R1",
        closed_at=NOW - timedelta(days=1),
    )
    assert age_defects((closed,), at=NOW).aged == ()


def test_defects_are_ordered_by_how_far_past_target_they_are():
    """Not by severity. A MINOR at 4x target needs attention before a fresh
    MAJOR that is still inside its commitment."""
    fresh_major = Defect("D-J", Severity.MAJOR, NOW - timedelta(days=1), against="R1")
    old_minor = Defect("D-M", Severity.MINOR, NOW - timedelta(days=150), against="R1")
    order = [a.defect.ref for a in age_defects((fresh_major, old_minor), at=NOW).aged]
    assert order == ["D-M", "D-J"]


def test_an_incoherent_ageing_policy_is_rejected_at_construction():
    with pytest.raises(ValueError, match="escalate < breach"):
        AgeingPolicy(escalate_multiple=5.0, breach_multiple=2.0)


def test_a_defect_raised_after_the_report_date_is_an_error_not_a_negative_age():
    with pytest.raises(ValueError, match="future"):
        age_defects(
            (Defect("D1", Severity.MINOR, NOW + timedelta(days=1), against="R1"),),
            at=NOW,
        )


# --- sign-off --------------------------------------------------------------


def sig(party: str, role: Role, org: str = "supplier") -> Signatory:
    return Signatory(party=party, role=role, organisation=org)


def test_an_approval_given_before_the_evidence_changed_is_stale():
    """Approving on Monday and failing a test on Wednesday does not leave you
    with an approved phase."""
    approvals = (
        Approval(sig("A", Role.TEST_MANAGER), Phase.SITE, NOW - timedelta(days=3)),
        Approval(sig("B", Role.QUALITY), Phase.SITE, NOW - timedelta(days=3)),
    )
    status = check_signoff(
        approvals, phase=Phase.SITE, evidence_last_changed=NOW - timedelta(days=1)
    )
    assert not status.satisfied
    assert len(status.stale_approvals) == 2


def test_one_person_cannot_hold_two_required_roles_for_the_same_phase():
    """Self-witnessed evidence is a claim, not evidence."""
    approvals = (
        Approval(sig("A", Role.TEST_MANAGER), Phase.SITE, NOW),
        Approval(sig("A", Role.QUALITY), Phase.SITE, NOW),
    )
    status = check_signoff(
        approvals, phase=Phase.SITE, evidence_last_changed=NOW - timedelta(days=1)
    )
    assert not status.satisfied
    assert status.independence_breaches


def test_customer_acceptance_from_inside_the_supplier_is_flagged():
    approvals = (
        Approval(sig("A", Role.TEST_MANAGER, "acme"), Phase.END_TO_END, NOW),
        Approval(sig("B", Role.QUALITY, "acme"), Phase.END_TO_END, NOW),
        Approval(sig("C", Role.CUSTOMER, "acme"), Phase.END_TO_END, NOW),
    )
    status = check_signoff(
        approvals,
        phase=Phase.END_TO_END,
        evidence_last_changed=NOW - timedelta(days=1),
    )
    assert not status.satisfied
    assert any("same organisation" in b for b in status.independence_breaches)


def test_a_complete_current_independent_signoff_is_satisfied():
    approvals = (
        Approval(sig("A", Role.TEST_MANAGER, "acme"), Phase.END_TO_END, NOW),
        Approval(sig("B", Role.QUALITY, "acme"), Phase.END_TO_END, NOW),
        Approval(sig("C", Role.CUSTOMER, "authority"), Phase.END_TO_END, NOW),
    )
    status = check_signoff(
        approvals,
        phase=Phase.END_TO_END,
        evidence_last_changed=NOW - timedelta(days=1),
    )
    assert status.satisfied
    assert status.missing_roles == ()


def test_a_missing_required_role_leaves_the_signoff_incomplete():
    approvals = (Approval(sig("A", Role.TEST_MANAGER), Phase.SITE, NOW),)
    status = check_signoff(
        approvals, phase=Phase.SITE, evidence_last_changed=NOW - timedelta(days=1)
    )
    assert Role.QUALITY in status.missing_roles


def test_a_qualified_approval_is_recorded_rather_than_silently_accepted():
    approvals = (
        Approval(
            sig("A", Role.TEST_MANAGER),
            Phase.SITE,
            NOW,
            qualified=True,
            note="subject to closure of D-12",
        ),
        Approval(sig("B", Role.QUALITY), Phase.SITE, NOW),
    )
    status = check_signoff(
        approvals,
        phase=Phase.SITE,
        evidence_last_changed=NOW - timedelta(days=1),
        policy=SignoffPolicy(),
    )
    assert status.satisfied
    assert "D-12" in status.qualified_approvals[0]


# --- evidence pack ---------------------------------------------------------


def test_the_pack_states_the_rule_that_was_applied_at_the_time():
    """Eighteen months later, the configuration is gone. The record must carry
    its own thresholds or it cannot be assessed."""
    ev = programme(site_ok=False)
    pack = build_pack(ev, build_matrix(ev, at=NOW), chain_for(ev), at=NOW)
    assert "Minimum verified fraction" in pack
    assert "Safety exempt from thresholds" in pack
    assert "Limitations of this pack" in pack


def test_the_pack_is_deterministic_for_the_same_input():
    """A record that differs between generations cannot be relied on."""
    ev = programme()
    args = (ev, build_matrix(ev, at=NOW), chain_for(ev))
    assert build_pack(*args, at=NOW) == build_pack(*args, at=NOW)


def test_the_pack_names_the_earliest_uncleared_phase_as_the_remedial_target():
    ev = programme(site_ok=False)
    pack = build_pack(ev, build_matrix(ev, at=NOW), chain_for(ev), at=NOW)
    assert "Earliest phase not cleared" in pack


def test_the_pack_carries_the_signoff_record_including_its_defects():
    ev = programme()
    status = check_signoff(
        (Approval(sig("A", Role.TEST_MANAGER), Phase.SITE, NOW),),
        phase=Phase.SITE,
        evidence_last_changed=NOW - timedelta(days=1),
    )
    pack = build_pack(
        ev,
        build_matrix(ev, at=NOW),
        chain_for(ev),
        at=NOW,
        signoffs=(status,),
    )
    assert "INCOMPLETE" in pack
    assert "quality" in pack
