import math
import datetime as dt
from typing import Dict, List, Tuple

import streamlit as st
import matplotlib.pyplot as plt
import numpy as np

# =========================================
# Page config
# =========================================
st.set_page_config(
    page_title="Postpartum Preeclampsia Risk Calculator",
    page_icon="🩺",
    layout="centered",
    initial_sidebar_state="expanded",
)

# Global (mobile-first) styles and sticky summary bar
st.markdown(
    """
    <style>
    :root { --base-font-size: 18px; }
    html, body, [class*="css"] { font-size: var(--base-font-size); line-height: 1.35; }
    h1, .stTitle { font-size: 1.6rem !important; }
    h2 { font-size: 1.35rem !important; }
    h3 { font-size: 1.2rem !important; }
    .stButton > button, .stDownloadButton > button {
        font-size: 1.08rem !important;
        padding: 0.9rem 1.1rem !important;
        border-radius: 14px !important;
        width: 100%;
    }
    .stRadio > label, .stCheckbox > label, .stTextInput > label, .stNumberInput > label {
        font-size: 1.05rem !important;
    }
    .stTextInput input, .stNumberInput input {
        font-size: 1.05rem !important;
        padding: 0.6rem !important;
    }
    .card {
        border: 1px solid #e5e7eb; border-radius: 16px; padding: 1rem;
        background-color: #ffffff; box-shadow: 0 1px 8px rgba(0,0,0,0.05);
    }
    /* Sticky summary bar */
    .sticky-summary {
        position: sticky; top: 0; z-index: 1000; backdrop-filter: blur(6px);
        background: rgba(255,255,255,0.85); border-bottom: 1px solid #eee;
        padding: 0.5rem 0.25rem; margin-bottom: 0.75rem;
    }
    .sticky-summary .metric { text-align: center; }
    .sticky-summary .metric .value { font-size: 1.15rem; font-weight: 700; }
    .sticky-summary .metric .label { font-size: 0.9rem; color: #555; }
    </style>
    """,
    unsafe_allow_html=True,
)

# =========================================
# Constants / Model
# =========================================
PER_POINT_MULTIPLIER = 1.3162897354903684  # ~+31.6% per point (empiric)
MAX_ABS_RISK = 0.95                         # cap to avoid >100%

# Hypertensive disorders — ordinal domain (take highest)
HTN_LEVELS: List[Tuple[str, int, str]] = [
    ("None", 0, "No chronic/gestational HTN, no edema/proteinuria codes"),
    ("Chronic HTN (I10)", 2, "Essential primary hypertension"),
    ("Gestational edema/proteinuria (O12)", 3, "Pregnancy-induced edema/proteinuria without HTN"),
    ("Gestational HTN (O13) or Unspecified HTN (O16)", 4, "Pregnancy-induced HTN or unspecified maternal HTN"),
]

# Other additive domains
DOMAINS: List[Tuple[str, int, str]] = [
    ("Renal: CKD (N18)", 2, "Chronic kidney disease"),
    ("Multiple gestation (O30)", 2, "Any multiple gestation"),
    ("Placental pathology (O43/O45)", 1, "Placental disorders and/or abruption"),
    ("Metabolic: Obesity (E66)", 1, "Overweight/obesity"),
    ("Metabolic: Diabetes in pregnancy (O24)", 1, "GDM/diabetes in pregnancy"),
    ("Autoimmune: SLE (M32)", 1, "Systemic lupus erythematosus"),
    ("Genetic screen abnormal (O28.5)", 1, "Abnormal chromosomal/genetic maternal screening"),
    ("Demographics: Black / African American", 1, "Self-identified race"),
    ("Demographics: Hispanic / Latino", 1, "Self-identified ethnicity"),
]

# Care-process (optional, prediction-only)
CARE_PROCESS: List[Tuple[str, int, str]] = [
    ("Cesarean w/o indication (O82)", 2, "Prediction use only; downstream of risk & decisions"),
    ("Supervision of high-risk pregnancy (O09)", 1, "Prediction use only; care labeling"),
]

# =========================================
# Helpers
# =========================================
def rr_from_points(points: int) -> float:
    return PER_POINT_MULTIPLIER ** points

def absolute_risk(rr: float, baseline_risk: float) -> float:
    return min(rr * baseline_risk, MAX_ABS_RISK)

def risk_bucket(rr: float) -> str:
    if rr < 2: return "Low"
    if rr < 4: return "Moderate"
    if rr < 6: return "High"
    return "Very high"

def pct(x: float) -> str:
    return f"{100*x:.1f}%"

def get_htn_points(selected_label: str) -> int:
    mapping = {name: pts for (name, pts, _hint) in HTN_LEVELS}
    return mapping.get(selected_label, 0)

def interpret_points_rr(points: int, rr: float, abs_risk: float) -> Tuple[str, str]:
    bucket = risk_bucket(rr)
    if points <= 2:
        cue = "Risk elevation is modest; routine postpartum BP checks may suffice per local protocol."
    elif points <= 4:
        cue = "Meaningful elevation; consider earlier follow-up (≤7 days) and symptom review."
    elif points <= 6:
        cue = "Substantial elevation; aligns with empiric higher-risk zone (≈4–5× baseline)."
    else:
        cue = "Very substantial elevation; emphasize reliable follow-up, low threshold for evaluation."
    msg = (
        f"**Category:** {bucket}\n\n"
        f"- **Score:** {points} points  \n"
        f"- **Relative risk:** {rr:.2f}× baseline  \n"
        f"- **Estimated absolute risk:** {pct(abs_risk)}  \n"
        f"- **Action cue:** {cue}"
    )
    return bucket, msg

def clinician_note(pid: str, points: int, rr: float, abs_risk: float, baseline: float,
                   htn_label: str, selected_domains: List[str], include_care: bool) -> str:
    today = dt.date.today().isoformat()
    domains_str = "; ".join(selected_domains) if selected_domains else "None selected"
    care_flag = "Included" if include_care else "Excluded"
    return (
        f"Postpartum Preeclampsia Risk Summary ({today})\n"
        f"Patient: {pid or 'N/A'}\n"
        f"Score: {points} | RR {rr:.2f}× | Abs risk {pct(abs_risk)} (baseline {pct(baseline)})\n"
        f"Hypertensive domain: {htn_label}\n"
        f"Other domains: {domains_str}\n"
        f"Care-process variables: {care_flag}\n"
        f"Method: Domain-weighted points (from multivariable Cox HRs); RR = 1.316^points; absolute risk = RR × baseline.\n"
        f"Decision support only; interpret within clinical context and local guidance."
    )

# -- Visualization utils (matplotlib) --
def risk_gauge(rr: float, ax=None):
    """
    Simple speedometer-like gauge (RR scale 1x to 8x).
    """
    rr_clamped = max(1.0, min(rr, 8.0))
    if ax is None:
        fig, ax = plt.subplots(subplot_kw={'projection': 'polar'}, figsize=(4.5, 3.2))
    else:
        fig = ax.figure
    ax.set_theta_direction(-1)   # clockwise
    ax.set_theta_zero_location('N')
    ax.set_rticks([])
    ax.set_axis_off()

    # Scale RR (1..8) to angle (-90deg to +90deg) => theta in radians
    # map: 1x -> -90deg; 8x -> +90deg
    def rr_to_theta(x):
        frac = (x - 1.0) / (8.0 - 1.0)
        return np.deg2rad(-90 + 180*frac)

    # background arcs for zones
    zones = [
        (1.0, 2.0, 0.0, 0.6),   # green-ish
        (2.0, 4.0, 0.12, 0.75), # yellow
        (4.0, 6.0, 0.08, 0.85), # orange
        (6.0, 8.0, 0.0, 0.9),   # red
    ]
    for lo, hi, hue, alpha in zones:
        thetas = np.linspace(rr_to_theta(lo), rr_to_theta(hi), 100)
        ax.plot(thetas, np.ones_like(thetas), lw=14, alpha=alpha)

    # needle
    theta_val = rr_to_theta(rr_clamped)
    ax.plot([theta_val, theta_val], [0.0, 1.0], lw=3)
    ax.scatter([theta_val], [1.0], s=40)

    # text
    ax.text(0.5*np.pi, -0.2, f"RR {rr:.2f}×", ha='center', va='center', transform=ax.transAxes, fontsize=12)
    return fig

def risk_color_bar(rr: float, baseline_risk: float, abs_risk: float):
    """
    Horizontal color-coded bar from 0% to ~20% absolute risk (cap display at 25%).
    """
    cap = 0.25
    plt.figure(figsize=(6.0, 1.1))
    ax = plt.gca()
    ax.set_xlim(0, cap)
    ax.set_ylim(0, 1)
    # gradient
    for x in np.linspace(0, cap, 256):
        ax.axvspan(x, x+cap/256, 0, 1, color=(1, 1 - min(1, x/cap), 0), linewidth=0)
    # markers
    ax.axvline(baseline_risk, color='k', linestyle='--', linewidth=1)
    ax.text(baseline_risk, 0.7, f"Baseline {pct(baseline_risk)}", ha='center', fontsize=9)
    ax.axvline(min(abs_risk, cap), color='k', linewidth=2)
    ax.text(min(abs_risk, cap), 0.15, f"Patient {pct(abs_risk)}", ha='center', fontsize=10, fontweight='bold')
    ax.set_xticks([0, 0.05, 0.10, 0.15, 0.20, 0.25])
    ax.set_xticklabels([f"{int(t*100)}%" for t in [0, .05, .10, .15, .20, .25]])
    ax.set_yticks([])
    ax.set_title("Absolute risk (visual guide)")
    st.pyplot(plt.gcf())
    plt.close()

def driver_breakdown_chart(breakdown: List[Tuple[str, int]]):
    """
    Horizontal bar chart by points contribution.
    """
    labels = [b[0] for b in breakdown if b[1] > 0]
    vals = [b[1] for b in breakdown if b[1] > 0]
    if not labels:
        st.info("No risk domains selected.")
        return
    order = np.argsort(vals)
    labels = [labels[i] for i in order]
    vals = [vals[i] for i in order]
    plt.figure(figsize=(6.2, 3.8))
    plt.barh(labels, vals)
    plt.xlabel("Points")
    plt.title("Risk drivers (points contribution)")
    st.pyplot(plt.gcf())
    plt.close()

def trajectory_curve(points_max: int, patient_points: int):
    pts = np.arange(0, points_max+1)
    rr_vals = PER_POINT_MULTIPLIER ** pts
    plt.figure(figsize=(6.0, 3.2))
    plt.plot(pts, rr_vals, marker='o')
    plt.scatter([patient_points], [PER_POINT_MULTIPLIER ** patient_points], s=60)
    plt.xlabel("Total points")
    plt.ylabel("Predicted RR vs baseline")
    plt.title("Risk trajectory by total points")
    st.pyplot(plt.gcf())
    plt.close()

# =========================================
# Sidebar (Settings)
# =========================================
st.sidebar.header("Settings")
baseline_risk_pct = st.sidebar.number_input(
    "Baseline absolute risk (0-factor, %)",
    min_value=0.1, max_value=20.0, value=3.8, step=0.1,
    help="Use incidence (%) from your 0-factor cohort. Default 3.8% based on your summaries."
)
baseline_risk = baseline_risk_pct / 100.0

include_care = st.sidebar.toggle(
    "Include care-process variables (prediction-only)?",
    value=False,
    help="If ON, O82 and O09 add points. For causal interpretation keep OFF; for prediction you may include."
)

# =========================================
# Header / Sticky Summary Shell
# =========================================
st.title("🩺 Postpartum Preeclampsia Risk Calculator")
st.caption("Mobile-optimized, graphical, and action-oriented. Domain-weighted score from a multivariable Cox model; RR validated against an empirical factor–risk curve.")

# Placeholder for sticky summary (populated after calculation)
summary_container = st.container()
with summary_container:
    st.markdown('<div class="sticky-summary"><div class="metric"><span class="label">Enter factors and tap “Calculate risk”.</span></div></div>', unsafe_allow_html=True)

# =========================================
# Input Form
# =========================================
with st.form("risk_form", clear_on_submit=False):
    st.subheader("Patient factors")

    st.markdown("**Hypertensive disorders (select highest applicable level):**")
    htn_label = st.radio(
        "Select one",
        options=[lvl[0] for lvl in HTN_LEVELS],
        index=0,
        captions=[lvl[2] for lvl in HTN_LEVELS],
        horizontal=False,
        label_visibility="collapsed",
    )

    st.markdown("**Other domains:**")
    flags: Dict[str, bool] = {}
    for name, pts, hint in DOMAINS:
        flags[name] = st.checkbox(name, help=hint)

    if include_care:
        st.markdown("**Care-process variables (optional; prediction-only):**")
        for name, pts, hint in CARE_PROCESS:
            flags[name] = st.checkbox(name, help=hint)

    st.markdown("---")
    patient_initials = st.text_input("Patient initials (optional, for note export)", value="", placeholder="AB, or leave blank")

    submitted = st.form_submit_button("Calculate risk", type="primary", use_container_width=True)

# =========================================
# Calculation & Outputs
# =========================================
def compute_points(selected_htn: str, flags: Dict[str, bool], include_care: bool):
    # HTN (ordinal)
    htn_pts = get_htn_points(selected_htn)
    breakdown = [("Hypertensive disorders", htn_pts)]
    selected_names = []
    total = htn_pts

    for name, pts, _ in DOMAINS:
        if flags.get(name, False):
            total += pts
            breakdown.append((name, pts))
            selected_names.append(name)

    if include_care:
        for name, pts, _ in CARE_PROCESS:
            if flags.get(name, False):
                total += pts
                breakdown.append((name, pts))
                selected_names.append(name)

    return total, breakdown, selected_names

if submitted:
    points, breakdown, selected_names = compute_points(htn_label, flags, include_care)
    rr = rr_from_points(points)
    abs_risk = absolute_risk(rr, baseline_risk)
    bucket, interp = interpret_points_rr(points, rr, abs_risk)

    # Update sticky summary
    st.markdown(
        f"""
        <div class="sticky-summary">
            <div style="display:flex; gap:10px; justify-content:space-around;">
                <div class="metric"><div class="value">{points}</div><div class="label">Total points</div></div>
                <div class="metric"><div class="value">{rr:.2f}×</div><div class="label">Relative risk</div></div>
                <div class="metric"><div class="value">{pct(abs_risk)}</div><div class="label">Absolute risk</div></div>
                <div class="metric"><div class="value">{bucket}</div><div class="label">Category</div></div>
            </div>
        </div>
        """,
        unsafe_allow_html=True
    )

    st.success("Risk calculated")

    # Summary card
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.markdown("### Result")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total points", points)
    c2.metric("Relative risk", f"{rr:.2f}×")
    c3.metric("Absolute risk", pct(abs_risk))
    c4.metric("Category", bucket)
    st.markdown(
        f"Computed as **RR = 1.316^points** and **Absolute risk = RR × baseline ({pct(baseline_risk)})**."
    )
    st.markdown('</div>', unsafe_allow_html=True)

    # Interpretation card
    st.markdown('<div class="card" style="margin-top: 0.75rem;">', unsafe_allow_html=True)
    st.markdown("### Interpretation & Action Cues")
    st.markdown(interp)
    st.markdown(
        """
**Context (non-directive):**
- Hypertensive disorders weigh most heavily; HTN domain is **ordinal** (use highest level only).
- Scores **5–6** align with a **substantially elevated** risk zone (~4–5× baseline).
- Align follow-up, BP checks, and counseling with **local protocols/ACOG guidance** and patient-specific factors.
        """
    )
    st.markdown('</div>', unsafe_allow_html=True)

    # Visuals row: Gauge + Color Bar
    left, right = st.columns(2)
    with left:
        st.markdown("#### Risk gauge")
        fig = risk_gauge(rr)
        st.pyplot(fig)
        plt.close(fig)
    with right:
        st.markdown("#### Absolute risk bar")
        risk_color_bar(rr, baseline_risk, abs_risk)

    # Driver breakdown
    st.markdown("#### Risk drivers")
    driver_breakdown_chart(breakdown)

    # Trajectory curve
    st.markdown("#### Trajectory: points → predicted RR")
    trajectory_curve(points_max=10, patient_points=points)

    # Clinician note: download + copy
    note = clinician_note(patient_initials, points, rr, abs_risk, baseline_risk, htn_label, selected_names, include_care)
    st.markdown("### Export")
    st.download_button(
        "Download clinician note (.txt)",
        data=note.encode("utf-8"),
        file_name=f"PPE_risk_{patient_initials or 'patient'}_{dt.date.today().isoformat()}.txt",
        mime="text/plain",
        use_container_width=True
    )
    st.markdown("Copy/paste into EMR:")
    st.code(note, language="text")

# =========================================
# Footer
# =========================================
st.divider()
with st.expander("Model provenance"):
    st.caption(
        "Weights derived from a multivariable Cox model (dominant HRs for O12/O13/O16), "
        "mapped to integers via ln(HR) relative to the empiric per-factor multiplier (≈1.316). "
        "The factor–risk curve (precision-weighted regression) explained ~96–99.8% of log-risk variance; "
        "diminishing marginal increases beyond 5–6 points."
    )
st.caption("For decision support; not a substitute for clinical judgment.")
