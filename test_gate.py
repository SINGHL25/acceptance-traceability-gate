"""Each test states a claim about how acceptance works, then holds the code to it.

These are not coverage filler. If one of these fails, either the code is wrong
or the domain claim in the test name is wrong — and finding out which is the
point of writing them this way.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from acceptance_gate import (
    Defect,
    Evidence,
    Execution,
    GateRule,
    Outcome,
    Phase,
    Requirement,
    Severity,
    TestCase,
    Verdict,
    build_matrix,
    evaluate,
)

NOW = datetime(2026, 3, 1, 9, 0, tzinfo=UTC)


def req(ref: str, **kw) -> Requirement:
    kw.setdefault("phase", Phase.SITE)
    return Requirement(ref=ref, text=f"obligation {ref}", **kw)


def tc(ref: str, covers: set[str], phase: Phase = Phase.SITE) -> TestCase:
    return TestCase(ref=ref, title=f"case {ref}", phase=phase, covers=frozenset(covers))


def ran(ref: str, verdict: Verdict, offset_min: int = 0) -> Execution:
    return Execution(
        test_ref=ref, verdict=verdict, executed_at=NOW + timedelta(minutes=offset_min)
    )


def gate(evidence: Evidence, rule: GateRule | None = None, phase=Phase.SITE):
    return evaluate(
        build_matrix(evidence, at=NOW), evidence.defects, phase=phase, rule=rule, at=NOW
    )


# --- timestamps ------------------------------------------------------------


def test_naive_timestamps_are_rejected_not_coerced():
    """An acceptance record that cannot say when it happened is not a record."""
    with pytest.raises(ValueError, match="timezone-aware"):
        Execution(test_ref="T1", verdict=Verdict.PASS, executed_at=datetime(2026, 3, 1))


def test_a_defect_cannot_close_before_it_was_raised():
    with pytest.raises(ValueError, match="closed before"):
        Defect(
            ref="D1",
            severity=Severity.MINOR,
            raised_at=NOW,
            against="R1",
            closed_at=NOW - timedelta(days=1),
        )


# --- traceability ----------------------------------------------------------


def test_a_requirement_with_no_covering_test_is_an_orphan_not_a_pass():
    """The commonest silent failure: nobody agreed to verify it, so it never
    appears in a pass rate, and its absence looks like success."""
    ev = Evidence(
        requirements=(req("R1"), req("R2")),
        tests=(tc("T1", {"R1"}),),
        executions=(ran("T1", Verdict.PASS),),
    )
    m = build_matrix(ev, at=NOW)
    assert [s.requirement.ref for s in m.orphan_requirements] == ["R2"]
    assert m.trace_coverage == 0.5
    assert m.verified_fraction == 0.5


def test_one_passing_test_does_not_verify_a_requirement_covered_by_two():
    """Partial evidence is not evidence. The passing test simply did not
    exercise whatever the failing one caught."""
    ev = Evidence(
        requirements=(req("R1"),),
        tests=(tc("T1", {"R1"}), tc("T2", {"R1"})),
        executions=(ran("T1", Verdict.PASS), ran("T2", Verdict.FAIL)),
    )
    status = build_matrix(ev, at=NOW).statuses[0]
    assert not status.is_verified
    assert status.failed == ("T2",)


def test_a_blocked_test_is_indeterminate_rather_than_failed():
    """Blocked tells you nothing about the requirement. Failed tells you
    something specific. Collapsing them corrupts the report in both directions."""
    ev = Evidence(
        requirements=(req("R1"),),
        tests=(tc("T1", {"R1"}),),
        executions=(ran("T1", Verdict.BLOCKED),),
    )
    status = build_matrix(ev, at=NOW).statuses[0]
    assert status.is_indeterminate
    assert not status.is_verified
    assert status.failed == ()


def test_a_retest_supersedes_the_earlier_result():
    """Fix, retest, pass is the normal path. A matrix that remembers the worst
    result ever recorded can never show a programme recovering."""
    ev = Evidence(
        requirements=(req("R1"),),
        tests=(tc("T1", {"R1"}),),
        executions=(
            ran("T1", Verdict.FAIL, offset_min=0),
            ran("T1", Verdict.PASS, offset_min=60),
        ),
    )
    assert build_matrix(ev, at=NOW).statuses[0].is_verified


def test_unverifiable_requirements_are_excluded_from_coverage():
    """Counting an untestable requirement in the denominator makes coverage
    permanently unreachable; counting it in the numerator inflates it."""
    ev = Evidence(
        requirements=(req("R1"), req("R2", verifiable=False)),
        tests=(tc("T1", {"R1"}),),
        executions=(ran("T1", Verdict.PASS),),
    )
    m = build_matrix(ev, at=NOW)
    assert m.trace_coverage == 1.0
    assert len(m.verifiable) == 1


def test_a_test_tracing_to_no_requirement_is_reported_not_ignored():
    ev = Evidence(
        requirements=(req("R1"),),
        tests=(tc("T1", {"R1"}), tc("T9", {"R-GHOST"})),
        executions=(ran("T1", Verdict.PASS),),
    )
    assert build_matrix(ev, at=NOW).orphan_tests == ("T9",)


# --- the gate --------------------------------------------------------------


def test_clean_evidence_accepts():
    ev = Evidence(
        requirements=(req("R1"),),
        tests=(tc("T1", {"R1"}),),
        executions=(ran("T1", Verdict.PASS),),
    )
    assert gate(ev).outcome is Outcome.ACCEPT


def test_an_open_critical_defect_withholds_regardless_of_coverage():
    """100% verified with the system broken is the report that ends careers."""
    ev = Evidence(
        requirements=(req("R1"),),
        tests=(tc("T1", {"R1"}),),
        executions=(ran("T1", Verdict.PASS),),
        defects=(Defect("D1", Severity.CRITICAL, NOW, against="R1"),),
    )
    d = gate(ev)
    assert d.outcome is Outcome.WITHHOLD
    assert d.verified_fraction == 1.0


def test_a_closed_defect_does_not_block():
    ev = Evidence(
        requirements=(req("R1"),),
        tests=(tc("T1", {"R1"}),),
        executions=(ran("T1", Verdict.PASS),),
        defects=(
            Defect(
                "D1",
                Severity.CRITICAL,
                NOW,
                against="R1",
                closed_at=NOW + timedelta(days=1),
            ),
        ),
    )
    assert gate(ev).outcome is Outcome.ACCEPT


def test_a_minor_defect_becomes_a_condition_rather_than_a_block():
    """Withholding acceptance over cosmetics is as much a failure of the gate
    as passing a broken system — it just costs money instead of credibility."""
    ev = Evidence(
        requirements=(req("R1"),),
        tests=(tc("T1", {"R1"}),),
        executions=(ran("T1", Verdict.PASS),),
        defects=(Defect("D1", Severity.MINOR, NOW, against="R1"),),
    )
    d = gate(ev)
    assert d.outcome is Outcome.ACCEPT_WITH_CONDITIONS
    assert d.blocking_reasons == ()
    assert len(d.conditions) == 1


def test_a_major_with_a_workaround_blocks_unless_the_rule_says_otherwise():
    """The concession is a named parameter someone signs, not a default."""
    ev = Evidence(
        requirements=(req("R1"),),
        tests=(tc("T1", {"R1"}),),
        executions=(ran("T1", Verdict.PASS),),
        defects=(Defect("D1", Severity.MAJOR, NOW, against="R1", workaround=True),),
    )
    assert gate(ev).outcome is Outcome.WITHHOLD
    lenient = GateRule(allow_major_with_workaround=True)
    assert gate(ev, lenient).outcome is Outcome.ACCEPT_WITH_CONDITIONS


def test_a_safety_requirement_is_not_subject_to_a_percentage_threshold():
    """A 95% threshold means one in twenty unverified. That is a reasonable
    commercial position and an unreasonable safety position."""
    reqs = tuple(req(f"R{i}") for i in range(1, 20)) + (
        req("R20", safety_related=True),
    )
    tests = tuple(tc(f"T{i}", {f"R{i}"}) for i in range(1, 21))
    execs = tuple(ran(f"T{i}", Verdict.PASS) for i in range(1, 20)) + (
        ran("T20", Verdict.BLOCKED),
    )
    ev = Evidence(requirements=reqs, tests=tests, executions=execs)
    d = gate(ev, GateRule(min_verified_fraction=0.95))
    assert d.verified_fraction == 0.95  # threshold met
    assert d.outcome is Outcome.WITHHOLD  # and it still withholds


def test_the_decision_carries_every_reason_it_relied_on():
    """A gate that returns a boolean cannot be defended six months later."""
    ev = Evidence(
        requirements=(req("R1"), req("R2")),
        tests=(tc("T1", {"R1"}),),
        executions=(ran("T1", Verdict.PASS),),
        defects=(Defect("D1", Severity.CRITICAL, NOW, against="R1"),),
    )
    d = gate(ev)
    assert len(d.reasons) >= 3
    assert all(r.detail for r in d.reasons)
    assert "WITHHOLD" in d.explain()


def test_the_gate_scopes_to_one_phase_at_a_time():
    """Site readiness is not held hostage by end-to-end work that has not begun."""
    ev = Evidence(
        requirements=(req("R1", phase=Phase.SITE), req("R2", phase=Phase.END_TO_END)),
        tests=(tc("T1", {"R1"}),),
        executions=(ran("T1", Verdict.PASS),),
    )
    assert gate(ev, phase=Phase.SITE).outcome is Outcome.ACCEPT
    assert gate(ev, phase=Phase.END_TO_END).outcome is Outcome.WITHHOLD


def test_severity_ordering_is_usable_as_a_threshold():
    assert Severity.CRITICAL < Severity.MAJOR < Severity.MINOR < Severity.TRIVIAL
    assert Severity.CRITICAL.blocks_acceptance
    assert not Severity.MINOR.blocks_acceptance


def test_a_test_case_covering_nothing_is_rejected_at_construction():
    with pytest.raises(ValueError, match="covers no requirement"):
        TestCase(ref="T1", title="orphan", phase=Phase.SITE)
