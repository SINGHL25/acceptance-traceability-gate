"""Requirements traceability.

The matrix answers two questions that a test-pass percentage cannot:

1. Which obligations has nobody agreed to verify?  (orphan requirements)
2. Which tests verify an obligation that does not exist? (orphan tests)

Both are silent failures. A programme can report 100% of tests passing while
a third of its requirements were never traced to a test at all.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .types import Evidence, Phase, Requirement, Verdict

__all__ = ["RequirementStatus", "Matrix", "build_matrix"]


@dataclass(frozen=True, slots=True)
class RequirementStatus:
    """Rolled-up state of one requirement across all tests that cover it."""

    requirement: Requirement
    covering_tests: tuple[str, ...]
    passed: tuple[str, ...]
    failed: tuple[str, ...]
    blocked: tuple[str, ...]
    not_run: tuple[str, ...]

    @property
    def is_orphan(self) -> bool:
        return not self.covering_tests

    @property
    def is_verified(self) -> bool:
        """Verified means *every* covering test passed.

        Not "at least one". If three tests cover a requirement and one fails,
        the requirement is not verified — the passing tests simply did not
        exercise the case that broke.
        """
        return bool(self.covering_tests) and len(self.passed) == len(
            self.covering_tests
        )

    @property
    def is_indeterminate(self) -> bool:
        """Nothing failed, but not everything ran. Neither pass nor fail."""
        return bool(self.covering_tests) and not self.failed and not self.is_verified


@dataclass(frozen=True, slots=True)
class Matrix:
    """The traceability matrix and the numbers derived from it."""

    statuses: tuple[RequirementStatus, ...]
    orphan_tests: tuple[str, ...]
    built_at: datetime

    def for_phase(self, phase: Phase) -> tuple[RequirementStatus, ...]:
        return tuple(s for s in self.statuses if s.requirement.phase is phase)

    @property
    def verifiable(self) -> tuple[RequirementStatus, ...]:
        """Coverage is only ever quoted against verifiable requirements."""
        return tuple(s for s in self.statuses if s.requirement.verifiable)

    @property
    def orphan_requirements(self) -> tuple[RequirementStatus, ...]:
        return tuple(s for s in self.verifiable if s.is_orphan)

    @property
    def trace_coverage(self) -> float:
        """Fraction of verifiable requirements with at least one covering test.

        This is a *plan* metric. It says the intent to verify exists. It says
        nothing about whether anything was executed.
        """
        pool = self.verifiable
        if not pool:
            return 1.0
        return sum(1 for s in pool if not s.is_orphan) / len(pool)

    @property
    def verified_fraction(self) -> float:
        """Fraction of verifiable requirements fully verified by passing tests.

        This is the *evidence* metric, and it is always the lower of the two.
        Quoting trace coverage and calling it progress is the classic sleight
        of hand in an acceptance report.
        """
        pool = self.verifiable
        if not pool:
            return 1.0
        return sum(1 for s in pool if s.is_verified) / len(pool)


def build_matrix(evidence: Evidence, *, at: datetime) -> Matrix:
    """Construct the traceability matrix from evidence.

    The latest execution wins per test case. Re-running a failed test after a
    fix is normal and the matrix must reflect the current state, not the worst
    state ever recorded.
    """
    if at.tzinfo is None:
        raise ValueError("`at` must be timezone-aware")

    latest: dict[str, Verdict] = {}
    seen_at: dict[str, datetime] = {}
    for ex in evidence.executions:
        prior = seen_at.get(ex.test_ref)
        if prior is None or ex.executed_at >= prior:
            latest[ex.test_ref] = ex.verdict
            seen_at[ex.test_ref] = ex.executed_at

    req_refs = {r.ref for r in evidence.requirements}
    covers: dict[str, list[str]] = {r.ref: [] for r in evidence.requirements}
    orphan_tests: list[str] = []

    for tc in evidence.tests:
        matched = [ref for ref in tc.covers if ref in req_refs]
        if not matched:
            orphan_tests.append(tc.ref)
        for ref in matched:
            covers[ref].append(tc.ref)

    statuses: list[RequirementStatus] = []
    for req in evidence.requirements:
        tests = tuple(sorted(covers[req.ref]))
        buckets: dict[Verdict, list[str]] = {v: [] for v in Verdict}
        for t in tests:
            buckets[latest.get(t, Verdict.NOT_RUN)].append(t)
        statuses.append(
            RequirementStatus(
                requirement=req,
                covering_tests=tests,
                passed=tuple(buckets[Verdict.PASS]),
                failed=tuple(buckets[Verdict.FAIL]),
                blocked=tuple(buckets[Verdict.BLOCKED]),
                not_run=tuple(buckets[Verdict.NOT_RUN]),
            )
        )

    return Matrix(
        statuses=tuple(statuses),
        orphan_tests=tuple(sorted(orphan_tests)),
        built_at=at,
    )
