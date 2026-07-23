"""Interactive acceptance gate.

Run locally:   streamlit run app.py
"""

from __future__ import annotations

import random
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

# The library lives under src/. Streamlit Cloud installs requirements.txt but
# does not install this project as a package, so put src/ on the path before
# importing. Harmless locally, where an editable install already resolves.
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

import altair as alt  # noqa: E402
import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from acceptance_gate import (  # noqa: E402
    PHASE_ORDER,
    AgeingPolicy,
    Approval,
    Defect,
    Evidence,
    Execution,
    GateRule,
    Outcome,
    Phase,
    Requirement,
    Role,
    Severity,
    Signatory,
    TestCase,
    Tier,
    Verdict,
    age_defects,
    build_matrix,
    build_pack,
    check_signoff,
    evaluate,
    evaluate_chain,
)

st.set_page_config(page_title="Acceptance Gate", page_icon="🚦", layout="wide")

NOW = datetime.now(UTC)

OUTCOME_STYLE = {
    Outcome.ACCEPT: ("#1a7f37", "ACCEPT"),
    Outcome.ACCEPT_WITH_CONDITIONS: ("#bf8700", "ACCEPT WITH CONDITIONS"),
    Outcome.WITHHOLD: ("#d4351c", "WITHHOLD"),
}
TIER_COLOUR = {
    Tier.WORKING: "#1a7f37",
    Tier.OVERDUE: "#bf8700",
    Tier.ESCALATED: "#d4351c",
    Tier.BREACHED: "#6f1d1b",
}


def banner(colour: str, label: str) -> None:
    st.markdown(
        f"<div style='background:{colour};color:#fff;padding:.9rem 1.2rem;"
        f"border-radius:8px;font-size:1.5rem;font-weight:700'>{label}</div>",
        unsafe_allow_html=True,
    )


def synthesise(cfg: dict) -> Evidence:
    """Reproducible synthetic programme. No real data, by design."""
    rng = random.Random(cfg["seed"])
    reqs: list[Requirement] = []
    tests: list[TestCase] = []
    execs: list[Execution] = []
    n = 0

    for phase in PHASE_ORDER:
        count = cfg["per_phase"]
        phase_reqs = []
        for _ in range(count):
            n += 1
            phase_reqs.append(
                Requirement(
                    ref=f"REQ-{n:03d}",
                    text=f"Synthetic obligation {n}",
                    phase=phase,
                    safety_related=(rng.random() < cfg["safety_rate"]),
                )
            )
        reqs.extend(phase_reqs)

        traced = phase_reqs[: max(0, count - cfg["gaps"][phase])]
        phase_tests = [
            TestCase(
                ref=f"TC-{r.ref[4:]}",
                title=f"Verify {r.ref}",
                phase=phase,
                covers=frozenset({r.ref}),
            )
            for r in traced
        ]
        tests.extend(phase_tests)

        pool = list(phase_tests)
        rng.shuffle(pool)
        n_fail = cfg["fails"][phase]
        failing = {t.ref for t in pool[:n_fail]}
        blocked = {t.ref for t in pool[n_fail : n_fail + cfg["blocked"][phase]]}
        for t in phase_tests:
            if t.ref in failing:
                v = Verdict.FAIL
            elif t.ref in blocked:
                v = Verdict.BLOCKED
            else:
                v = Verdict.PASS
            execs.append(
                Execution(
                    test_ref=t.ref,
                    verdict=v,
                    executed_at=NOW - timedelta(hours=rng.randint(1, 400)),
                    witnessed_by="witness",
                )
            )

    return Evidence(tuple(reqs), tuple(tests), tuple(execs))


st.title("🚦 Acceptance gate")
st.caption(
    "Requirements traceability, phase-gate chain, defect ageing and sign-off "
    "for a field-deployed system. Synthetic data only."
)

with st.sidebar:
    st.header("Programme")
    per_phase = st.slider("Requirements per phase", 5, 60, 20, step=5)
    safety_rate = st.slider("Safety-related share", 0.0, 0.3, 0.05, 0.01)
    seed = st.number_input("Seed", 0, 9999, 7)

    st.header("Evidence gaps")
    st.caption("Per phase: requirements with no test, tests failing, tests blocked.")
    gaps: dict[Phase, int] = {}
    fails: dict[Phase, int] = {}
    blocked_n: dict[Phase, int] = {}
    for p in PHASE_ORDER:
        with st.expander(p.value, expanded=(p is Phase.SITE)):
            gaps[p] = st.slider("no test", 0, 10, 0, key=f"g{p}")
            fails[p] = st.slider(
                "failing", 0, 10, 1 if p is Phase.SITE else 0, key=f"f{p}"
            )
            blocked_n[p] = st.slider("blocked", 0, 10, 0, key=f"b{p}")

    st.header("Defects")
    n_crit = st.slider("Open CRITICAL", 0, 5, 0)
    n_major = st.slider("Open MAJOR", 0, 8, 2)
    major_workaround = st.checkbox("MAJOR have a workaround", value=True)
    n_minor = st.slider("Open MINOR", 0, 15, 5)
    max_age = st.slider("Oldest defect (days)", 1, 200, 45)

    st.header("Gate rule")
    st.caption("Signed parameters, not constants in code.")
    min_trace = st.slider("Min trace coverage", 0.0, 1.0, 1.0, 0.01)
    min_verified = st.slider("Min verified fraction", 0.0, 1.0, 0.95, 0.01)
    allow_major = st.checkbox("Concede MAJOR with workaround", value=False)
    safety_strict = st.checkbox("Safety exempt from thresholds", value=True)

cfg = {
    "per_phase": per_phase,
    "safety_rate": safety_rate,
    "seed": int(seed),
    "gaps": gaps,
    "fails": fails,
    "blocked": blocked_n,
}
base = synthesise(cfg)
targets = [r.ref for r in base.requirements]
rng = random.Random(int(seed) + 1)

defects: list[Defect] = []
for i in range(n_crit):
    defects.append(
        Defect(
            f"DEF-C{i + 1}",
            Severity.CRITICAL,
            NOW - timedelta(days=rng.randint(1, max_age)),
            against=targets[rng.randrange(len(targets))],
        )
    )
for i in range(n_major):
    defects.append(
        Defect(
            f"DEF-J{i + 1}",
            Severity.MAJOR,
            NOW - timedelta(days=rng.randint(1, max_age)),
            against=targets[rng.randrange(len(targets))],
            workaround=major_workaround,
        )
    )
for i in range(n_minor):
    defects.append(
        Defect(
            f"DEF-M{i + 1}",
            Severity.MINOR,
            NOW - timedelta(days=rng.randint(1, max_age)),
            against=targets[rng.randrange(len(targets))],
        )
    )

evidence = Evidence(base.requirements, base.tests, base.executions, tuple(defects))
rule = GateRule(
    min_trace_coverage=min_trace,
    min_verified_fraction=min_verified,
    allow_major_with_workaround=allow_major,
    safety_requires_full_verification=safety_strict,
)
matrix = build_matrix(evidence, at=NOW)
chain = evaluate_chain(matrix, evidence.defects, rule=rule, at=NOW)
ageing = AgeingPolicy()
summary = age_defects(evidence.defects, at=NOW, policy=ageing)

tab_chain, tab_phase, tab_def, tab_sign, tab_pack = st.tabs(
    ["Phase chain", "Phase detail", "Defect ageing", "Sign-off", "Evidence pack"]
)

# --- phase chain -----------------------------------------------------------
with tab_chain:
    blocking = chain.blocking_phase
    if blocking is None:
        banner("#1a7f37", "ALL PHASES CLEARED")
    else:
        banner("#d4351c", f"EARLIEST PHASE NOT CLEARED — {blocking.value.upper()}")
    st.caption(
        "The chain reports the *earliest* failing phase. Pointing at the latest "
        "one sends the programme after symptoms rather than the upstream cause."
    )

    cols = st.columns(len(chain.states))
    for col, s in zip(cols, chain.states, strict=True):
        with col:
            if s.cleared:
                colour = "#1a7f37"
            elif not s.entry_met:
                colour = "#6e7781"
            else:
                colour = "#d4351c"
            st.markdown(
                f"<div style='border-left:6px solid {colour};padding:.4rem .8rem'>"
                f"<b>{s.phase.value}</b><br/>"
                f"<span style='color:{colour};font-weight:600'>{s.status}</span>"
                f"</div>",
                unsafe_allow_html=True,
            )
            st.metric("Verified", f"{s.decision.verified_fraction:.0%}")
            st.caption(s.entry_criteria)

    st.code(chain.explain(), language="text")

# --- phase detail ----------------------------------------------------------
with tab_phase:
    phase = st.selectbox("Phase", list(PHASE_ORDER), format_func=lambda p: p.value)
    decision = evaluate(matrix, evidence.defects, phase=phase, rule=rule, at=NOW)
    colour, label = OUTCOME_STYLE[decision.outcome]
    banner(colour, label)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Trace coverage", f"{decision.trace_coverage:.1%}", help="The plan")
    c2.metric("Verified", f"{decision.verified_fraction:.1%}", help="The evidence")
    c3.metric("Blocking", len(decision.blocking_reasons))
    c4.metric("Conditions", len(decision.conditions))
    st.info(
        "**Trace coverage is always the flattering number.** It counts intent. "
        "Verified counts evidence. Quoting the first as progress is the classic "
        "sleight of hand in an acceptance report."
    )

    left, right = st.columns([3, 2])
    with left:
        st.subheader("Traceability matrix")
        scoped = [s for s in matrix.for_phase(phase) if s.requirement.verifiable]
        rows = []
        for i, s in enumerate(scoped):
            if s.is_orphan:
                state = "No test"
            elif s.failed:
                state = "Failed"
            elif s.is_verified:
                state = "Verified"
            else:
                state = "Indeterminate"
            rows.append(
                {
                    "ref": s.requirement.ref,
                    "state": state,
                    "safety": "yes" if s.requirement.safety_related else "",
                    "row": i // 10,
                    "col": i % 10,
                }
            )
        if rows:
            chart = (
                alt.Chart(pd.DataFrame(rows))
                .mark_rect(stroke="white", strokeWidth=2)
                .encode(
                    x=alt.X("col:O", axis=None),
                    y=alt.Y("row:O", axis=None),
                    color=alt.Color(
                        "state:N",
                        scale=alt.Scale(
                            domain=["Verified", "Indeterminate", "Failed", "No test"],
                            range=["#1a7f37", "#bf8700", "#d4351c", "#6e7781"],
                        ),
                        legend=alt.Legend(title=None, orient="bottom"),
                    ),
                    tooltip=["ref", "state", "safety"],
                )
                .properties(height=260)
            )
            st.altair_chart(chart, use_container_width=True)
    with right:
        st.subheader("Findings")
        if not decision.reasons:
            st.success("No findings.")
        for r in decision.reasons:
            icon = "🔴" if r.blocking else "🟡"
            with st.expander(f"{icon} {r.detail}", expanded=r.blocking):
                st.caption(f"`{r.finding.value}`")
                if r.refs:
                    st.code(", ".join(r.refs[:40]))
    st.code(decision.explain(), language="text")

# --- defect ageing ---------------------------------------------------------
with tab_def:
    st.subheader("Severity is a static picture. Age is the missing dimension.")
    st.caption(
        "A CRITICAL raised this morning and a CRITICAL open eleven weeks are the "
        "same row in most defect reports. The first is being worked; the second "
        "is being tolerated."
    )
    counts = summary.counts()
    cols = st.columns(4)
    for col, tier in zip(cols, Tier, strict=True):
        col.metric(tier.value, counts[tier.value])

    if summary.aged:
        df = pd.DataFrame(
            [
                {
                    "ref": a.defect.ref,
                    "severity": a.defect.severity.name,
                    "age_days": round(a.age_days, 1),
                    "x_target": round(a.ratio, 2),
                    "tier": a.tier.value,
                    "against": a.defect.against,
                }
                for a in summary.aged
            ]
        )
        chart = (
            alt.Chart(df)
            .mark_bar()
            .encode(
                x=alt.X("x_target:Q", title="age as a multiple of target"),
                y=alt.Y("ref:N", sort="-x", title=None),
                color=alt.Color(
                    "tier:N",
                    scale=alt.Scale(
                        domain=[t.value for t in Tier],
                        range=[TIER_COLOUR[t] for t in Tier],
                    ),
                    legend=alt.Legend(title=None, orient="bottom"),
                ),
                tooltip=list(df.columns),
            )
            .properties(height=max(220, 22 * len(df)))
        )
        st.altair_chart(chart, use_container_width=True)
        st.dataframe(df, use_container_width=True, hide_index=True)
    st.code(summary.explain(), language="text")

# --- sign-off --------------------------------------------------------------
with tab_sign:
    st.subheader("A gate decision is an input to a signature, not a substitute")
    sign_phase = st.selectbox(
        "Phase", list(PHASE_ORDER), format_func=lambda p: p.value, key="signphase"
    )
    c1, c2 = st.columns(2)
    with c1:
        same_person = st.checkbox("Same person signs manager + quality", value=False)
        same_org = st.checkbox("Customer signs from the supplier org", value=False)
    with c2:
        signed_late = st.checkbox("Approvals predate the last evidence", value=False)
        qualified = st.checkbox("Manager signs subject to conditions", value=False)

    signed_at = NOW - timedelta(days=5 if signed_late else 0)
    approvals = (
        Approval(
            Signatory("R. Patel", Role.TEST_MANAGER, "supplier"),
            sign_phase,
            signed_at,
            qualified=qualified,
            note="subject to closure of DEF-J1" if qualified else "",
        ),
        Approval(
            Signatory(
                "R. Patel" if same_person else "L. Novak", Role.QUALITY, "supplier"
            ),
            sign_phase,
            signed_at,
        ),
        Approval(
            Signatory(
                "M. Ferreira",
                Role.CUSTOMER,
                "supplier" if same_org else "authority",
            ),
            sign_phase,
            signed_at,
        ),
    )
    status = check_signoff(
        approvals, phase=sign_phase, evidence_last_changed=NOW - timedelta(days=1)
    )
    banner(
        "#1a7f37" if status.satisfied else "#d4351c",
        "SIGN-OFF COMPLETE" if status.satisfied else "SIGN-OFF INCOMPLETE",
    )
    st.code(status.explain(), language="text")
    st.caption(
        "Independence: self-witnessed evidence is a claim, not evidence. "
        "Currency: approving on Monday and failing a test on Wednesday does not "
        "leave you with an approved phase."
    )

# --- evidence pack ---------------------------------------------------------
with tab_pack:
    st.subheader("The artefact that outlives the programme")
    st.caption(
        "Deterministic for a given input, and it states its own thresholds "
        "inline so the decision can be assessed in fifteen years without the "
        "original configuration."
    )
    signoffs = tuple(
        check_signoff(
            (
                Approval(Signatory("R. Patel", Role.TEST_MANAGER, "supplier"), p, NOW),
                Approval(Signatory("L. Novak", Role.QUALITY, "supplier"), p, NOW),
                Approval(Signatory("M. Ferreira", Role.CUSTOMER, "authority"), p, NOW),
            ),
            phase=p,
            evidence_last_changed=NOW - timedelta(days=1),
        )
        for p in PHASE_ORDER
    )
    pack = build_pack(
        evidence,
        matrix,
        chain,
        at=NOW,
        rule=rule,
        ageing=ageing,
        signoffs=signoffs,
    )
    st.download_button(
        "⬇ Download evidence pack (Markdown)",
        pack,
        file_name="acceptance-evidence-pack.md",
        mime="text/markdown",
    )
    st.markdown(pack)
