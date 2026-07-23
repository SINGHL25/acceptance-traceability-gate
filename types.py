"""Domain types for acceptance gating.

Every timestamp in this library is timezone-aware. Naive datetimes are
rejected at construction, not silently coerced: an acceptance decision that
cannot say *when* it was made is not an acceptance decision.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import IntEnum, StrEnum

__all__ = [
    "Severity",
    "Verdict",
    "Phase",
    "Requirement",
    "TestCase",
    "Execution",
    "Defect",
    "Evidence",
]


def _require_aware(ts: datetime, field_name: str) -> None:
    if ts.tzinfo is None or ts.tzinfo.utcoffset(ts) is None:
        raise ValueError(f"{field_name} must be timezone-aware, got naive {ts!r}")


class Severity(IntEnum):
    """Defect severity. Ordered so that comparison means what it looks like.

    The ordering is deliberate: ``Severity.CRITICAL > Severity.MINOR``. Gate
    rules are written as thresholds, and a threshold on an unordered enum is a
    bug waiting to happen.
    """

    CRITICAL = 1  # function unavailable, no workaround, revenue or safety impact
    MAJOR = 2  # function impaired, workaround exists but is not sustainable
    MINOR = 3  # function correct, behaviour degraded or cosmetic under load
    TRIVIAL = 4  # cosmetic only, no functional consequence

    @property
    def blocks_acceptance(self) -> bool:
        """CRITICAL and MAJOR block by default. See ``GateRule`` to override."""
        return self <= Severity.MAJOR


class Verdict(StrEnum):
    """Result of executing a test case.

    ``BLOCKED`` is not a failure. Conflating the two is the most common way a
    coverage report lies: a blocked test tells you nothing about the
    requirement, whereas a failed test tells you something quite specific.
    """

    PASS = "pass"
    FAIL = "fail"
    BLOCKED = "blocked"
    NOT_RUN = "not_run"


class Phase(StrEnum):
    """Generic acceptance phases for a deployed field system."""

    FACTORY = "factory"  # bench, supplier premises, simulated interfaces
    SITE = "site"  # installed hardware, real interfaces, one location
    INTEGRATION = "integration"  # subsystems joined, live upstream/downstream
    END_TO_END = "end_to_end"  # full transaction chain under production config


@dataclass(frozen=True, slots=True)
class Requirement:
    """A single verifiable obligation.

    ``verifiable`` is not decoration. A requirement no test can falsify cannot
    be accepted or rejected, and counting it in a coverage percentage inflates
    the number with something meaningless.
    """

    ref: str
    text: str
    phase: Phase
    verifiable: bool = True
    safety_related: bool = False

    def __post_init__(self) -> None:
        if not self.ref.strip():
            raise ValueError("requirement ref must not be empty")


@dataclass(frozen=True, slots=True)
class TestCase:
    """A procedure that verifies one or more requirements."""

    ref: str
    title: str
    phase: Phase
    covers: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        if not self.covers:
            raise ValueError(
                f"test case {self.ref} covers no requirement; "
                "an untraced test consumes effort and proves nothing"
            )


@dataclass(frozen=True, slots=True)
class Execution:
    """One run of one test case at a point in time."""

    test_ref: str
    verdict: Verdict
    executed_at: datetime
    witnessed_by: str | None = None

    def __post_init__(self) -> None:
        _require_aware(self.executed_at, "executed_at")


@dataclass(frozen=True, slots=True)
class Defect:
    """A raised defect, open until closed."""

    ref: str
    severity: Severity
    raised_at: datetime
    against: str  # requirement ref
    closed_at: datetime | None = None
    workaround: bool = False

    def __post_init__(self) -> None:
        _require_aware(self.raised_at, "raised_at")
        if self.closed_at is not None:
            _require_aware(self.closed_at, "closed_at")
            if self.closed_at < self.raised_at:
                raise ValueError(f"defect {self.ref} closed before it was raised")

    @property
    def is_open(self) -> bool:
        return self.closed_at is None


@dataclass(frozen=True, slots=True)
class Evidence:
    """Everything the gate is allowed to consider. Nothing else counts."""

    requirements: tuple[Requirement, ...]
    tests: tuple[TestCase, ...]
    executions: tuple[Execution, ...]
    defects: tuple[Defect, ...] = ()
