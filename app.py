"""fmeda-toolkit dashboard.

    pip install streamlit pydantic pyyaml openpyxl pandas
    streamlit run app.py

PUBLIC DEMO. Ships with a fictional ECU preloaded so it opens in a working
state. Nothing here is real, and nothing real should be uploaded to a hosted
copy of it — see the banner in the sidebar.

Architecture note: this file is presentation only. Every number comes from
fmeda.metrics, every derating from fmeda.policy, every cell from fmeda.report.
Keeping the deterministic core importable and testable, with the UI as a thin
shell over it, is what lets the same engine run in CI against a repository of
analyses. A dashboard that owns the arithmetic can't be unit tested and can't
be trusted.
"""

from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path

import pandas as pd
import streamlit as st

from fmeda import policy as P
from fmeda.metrics import compute
from fmeda.models import load_analysis, validate_analysis

EXAMPLE = Path(__file__).parent / "examples" / "bjb" / "fmeda.yaml"

# Component failure-rate sources. IEC TR 62380 was withdrawn on 2017-02-17 and
# replaced by IEC 61709:2017 — it stays selectable only so a new analysis can
# be compared against an older one, and it is labelled everywhere it appears.
FR_SOURCES = {
    "IEC 61709:2017": "Current. Reference conditions and stress models for failure rate data.",
    "SN 29500 (Siemens Norm)": "Widely used component failure rate data, per part family.",
    "IEC TR 62380:2004 — WITHDRAWN": (
        "Withdrawn 2017-02-17, replaced by IEC 61709:2017. Offered for comparison "
        "with legacy analyses only. Do not use for new work."
    ),
}

TEMP_PROFILES = {
    "Passenger compartment — 25 °C mean": 25,
    "Underhood, ambient — 40 °C mean": 40,
    "Underhood, near engine — 70 °C mean": 70,
    "Power electronics enclosure — 85 °C mean": 85,
}

UPLOAD_SLOTS = [
    (P.DocCategory.SCHEMATIC, "Circuit schematic — netlist + BOM", True,
     "Netlist and bill of materials exported from your EDA tool (.net, .cir, .csv). "
     "A PDF drawing is not enough: connectivity has to be machine-readable for the "
     "propagation analysis to mean anything.",
     ["net", "cir", "csv", "xml", "kicad_sch"]),
    (P.DocCategory.SAFETY_MANUAL, "Supplier safety manual", False,
     "Substantiates supplier diagnostic coverage claims. Without it every "
     "supplier_claim drops one evidence tier.", ["pdf", "docx", "md"]),
    (P.DocCategory.SAFETY_CONCEPT, "Technical safety concept", False,
     "Source for safety goals, ASIL and FTTI.", ["pdf", "docx", "md"]),
    (P.DocCategory.DESIGN_DOC, "Detailed design document", False,
     "Lets failure effects be traced to circuit function.", ["pdf", "docx", "md"]),
    (P.DocCategory.HARA, "HARA", False,
     "Independent check on ASIL assignment per goal.", ["pdf", "docx", "xlsx"]),
]


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


st.set_page_config(page_title="fmeda-toolkit", layout="wide", page_icon="🛡")

st.markdown(
    """
    <style>
      .stApp { font-family: Arial, Helvetica, sans-serif; }
      .band { border-left: 3px solid #0F5F63; padding: 10px 16px; margin: 6px 0 14px;
              background: rgba(15,95,99,0.06); }
      .warn { border-left: 3px solid #8E5309; padding: 10px 16px; margin: 6px 0 14px;
              background: rgba(142,83,9,0.08); }
      .muted { color: #55676A; font-size: 0.86rem; }
    </style>
    """,
    unsafe_allow_html=True,
)

# --------------------------------------------------------------------------
# Sidebar — analysis setup
# --------------------------------------------------------------------------
with st.sidebar:
    st.markdown("### Analysis setup")
    st.markdown(
        '<div class="warn"><b>Demo build.</b> Fictional ECU, invented failure rates. '
        "Do not upload real schematics, supplier data or safety documents to a hosted "
        "copy of this tool.</div>",
        unsafe_allow_html=True,
    )

    st.markdown("**Temperature profile**")
    temp_profile = st.selectbox("Mission temperature", list(TEMP_PROFILES), index=1,
                               label_visibility="collapsed")

    st.markdown("**Component failure rate source**")
    fr_source = st.selectbox("Source", list(FR_SOURCES), index=1,
                            label_visibility="collapsed")
    st.caption(FR_SOURCES[fr_source])
    if "WITHDRAWN" in fr_source:
        st.warning("IEC TR 62380 was withdrawn on 2017-02-17 and replaced by "
                   "IEC 61709:2017. Results carry a withdrawn-source flag.", icon="⚠")

    st.markdown("**Conservatism**")
    level = st.select_slider(
        "Level", options=list(P.Level), value=P.Level.CONSERVATIVE,
        format_func=lambda lv: lv.label, label_visibility="collapsed",
    )
    st.caption(level.blurb)
    st.markdown(
        '<div class="muted">These are deterministic derating rules, not a statistical '
        "confidence interval. The same inputs at the same level always give the same "
        "numbers.</div>",
        unsafe_allow_html=True,
    )

# --------------------------------------------------------------------------
# Inputs
# --------------------------------------------------------------------------
st.title("FMEDA analysis")
st.markdown(
    '<div class="band">Upload a netlist and BOM, point at a failure-rate source, and '
    "get ISO 26262-5 hardware architectural metrics per safety goal — with the "
    "reasoning behind every classification written into the report.</div>",
    unsafe_allow_html=True,
)

uploads: list[dict] = []
present: set[P.DocCategory] = {P.DocCategory.TEMP_PROFILE, P.DocCategory.COMPONENT_DATA}

st.subheader("1 · Inputs")
left, right = st.columns(2)
for i, (category, label, required, help_text, types) in enumerate(UPLOAD_SLOTS):
    with (left if i % 2 == 0 else right):
        files = st.file_uploader(
            f"{label}{' *' if required else ''}", type=types,
            accept_multiple_files=True, help=help_text, key=category.value,
        )
        if files:
            present.add(category)
            for f in files:
                uploads.append({"category": category.value, "name": f.name,
                                "digest": digest(f.getvalue())})
        else:
            st.caption(help_text)

use_example = st.checkbox(
    "Use the bundled fictional ECU (Battery Junction Box Controller)", value=True,
    help="The demo dataset. Uncheck once schematic parsing is wired to your own netlist.",
)
if use_example:
    present.add(P.DocCategory.SCHEMATIC)
    uploads.append({"category": "schematic", "name": "examples/bjb/fmeda.yaml (bundled)",
                    "digest": digest(EXAMPLE.read_bytes())})

# --------------------------------------------------------------------------
# Completeness gate
# --------------------------------------------------------------------------
st.subheader("2 · Completeness")
blocking, advisory = P.missing_documents(present)

if blocking:
    st.error("Cannot run without: " + ", ".join(sorted(b.value for b in blocking)), icon="🚫")
elif advisory:
    st.warning(
        "**More reference documents give a more precise analysis.** These are missing — "
        "each one costs something specific:", icon="📄",
    )
    for category in sorted(advisory, key=lambda c: c.value):
        st.markdown(f"- **{category.value}** — {P.MISSING_DOC_EFFECT[category]}")
    st.caption("You can proceed. The report records what was missing and what it cost.")
else:
    st.success("All reference documents provided. No evidence tier is degraded by a "
               "missing document.", icon="✅")

proceed = st.checkbox("I have uploaded everything available for this item", value=bool(advisory))

# --------------------------------------------------------------------------
# Run
# --------------------------------------------------------------------------
st.subheader("3 · Analysis")
if blocking or not proceed:
    st.info("Complete the steps above to run the analysis.")
    st.stop()

analysis, parts = load_analysis(EXAMPLE)
problems = validate_analysis(analysis, parts)
errors = [p for p in problems if p.startswith("error:")]
warnings = [p for p in problems if p.startswith("warn:")]

if errors:
    st.error("Input validation failed:")
    for e in errors:
        st.markdown(f"- {e[7:]}")
    st.stop()
for w in warnings:
    st.warning(w[6:], icon="⚠")

result = P.apply(analysis, parts, level, present)
goals = compute(result.analysis, parts)

cols = st.columns(len(goals))
for col, (goal_id, goal_result) in zip(cols, goals.items(), strict=True):
    target = result.analysis.target_for(result.analysis.safety_goals[goal_id].asil)
    met = goal_result.spfm >= target.spfm and goal_result.lfm >= target.lfm
    with col:
        st.markdown(f"**{goal_id} · ASIL {goal_result.asil}** — "
                    f"{'targets met' if met else 'targets NOT met'}")
        st.metric("SPFM", f"{goal_result.spfm:.2%}",
                  f"{(goal_result.spfm - target.spfm) * 100:+.2f} pp vs target")
        st.metric("LFM", f"{goal_result.lfm:.2%}",
                  f"{(goal_result.lfm - target.lfm) * 100:+.2f} pp vs target")
        st.metric("PMHF (lower bound)", f"{goal_result.pmhf_fit:.2f} FIT",
                  f"target < {target.pmhf_fit:.0f} FIT", delta_color="off")

st.caption(
    "PMHF is a lower bound — single-point and residual terms only. The dual-point "
    "failure term is not modelled in this version."
)

st.markdown("#### Why each fault is safety critical")
st.caption(
    "Every single-point and residual fault, with the reasoning that put it in that class. "
    "This text is written into the report's rationale column verbatim."
)
tabs = st.tabs(list(goals))
for tab, goal_result in zip(tabs, goals.values(), strict=True):
    with tab:
        ranked = goal_result.residual_ranking()
        if not ranked:
            st.success("No single-point or residual faults against this goal.")
            continue
        st.dataframe(
            pd.DataFrame([{
                "Element": r.element, "Failure mode": r.mode, "Class": r.fault_class,
                "λ mode (FIT)": round(r.lambda_mode, 3),
                "Uncovered (FIT)": round(r.split.spf + r.split.rf, 3),
                "DC applied": f"{r.dc_applied:.1%}",
                "Mechanism": ", ".join(r.mechanisms) or "—",
                "Rationale": r.rationale,
            } for r in ranked]),
            width="stretch", hide_index=True,
        )

if result.actions:
    with st.expander(f"Conservatism policy changed {len(result.actions)} value(s)"):
        st.dataframe(
            pd.DataFrame([{"Target": a.target, "Field": a.field_name, "Before": a.before,
                           "After": a.after, "Reason": a.reason} for a in result.actions]),
            width="stretch", hide_index=True,
        )

if result.review_queue:
    with st.expander(f"⚠ {len(result.review_queue)} item(s) need analyst resolution"):
        for item in result.review_queue:
            st.markdown(f"- {item}")

# --------------------------------------------------------------------------
# Report
# --------------------------------------------------------------------------
st.subheader("4 · Report")
st.caption("One sheet per safety goal, plus the mechanism register, the policy actions, "
           "the review queue and a provenance sheet recording exactly what went in.")

if st.button("Generate Excel report", type="primary"):
    from fmeda.report import write_report

    out = Path(tempfile.mkdtemp()) / f"FMEDA_{result.analysis.meta.variant or 'report'}.xlsx"
    write_report(out, analysis, parts, result, goals, uploads, present,
                 fr_source, temp_profile)
    st.download_button("Download report", out.read_bytes(), file_name=out.name,
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    st.success(f"Generated {out.name}", icon="📊")

st.divider()
st.caption(
    "Machine-generated classifications are proposals. Nothing here is a released FMEDA "
    "until an analyst has ratified every row."
)
