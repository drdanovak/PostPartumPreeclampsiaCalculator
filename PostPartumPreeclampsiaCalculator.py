import math
import datetime as dt
import streamlit as st

# -----------------------------
# Config & constants
# -----------------------------
st.set_page_config(
    page_title="Postpartum Preeclampsia Risk Calculator",
    page_icon="🩺",
    layout="centered",
    initial_sidebar_state="expanded",
)

# >>> MOBILE-FRIENDLY STYLES <<<
st.markdown(
    """
    <style>
    :root {
        --base-font-size: 18px; /* bump global font size for mobile readability */
    }
    html, body, [class*="css"]  {
        font-size: var(--base-font-size);
        line-height: 1.35;
    }
    h1, .stTitle { font-size: 1.6rem !important; }
    h2 { font-size: 1.35rem !important; }
    h3 { font-size: 1.2rem !important; }
    .stButton > button {
        font-size: 1.1rem !important;
        padding: 0.9rem 1.1rem !important;
        border-radius: 12px !important;
        width: 100%;
    }
    .stDownloadButton > button {
        font-size: 1.05rem !important;
        padding: 0.7rem 1rem !important;
        border-radius: 12px !important;
        width: 100%;
    }
    .stRadio > label, .stCheckbox > label, .stSlider > label {
        font-size: 1.05rem !important;
    }
    .stRadio div[role="radiogroup"] > label, .stCheckbox > label {
        padding: 0.35rem 0.2rem;
    }
    .stTextInput > div > div > input, .stNumberInput input {
        font-size: 1.05rem !important;
        padding: 0.6rem !important;
    }
    .metric-label, [data-testid="stMetricValue"] {
        font-size: 1.05rem !important;
    }
    /* Improve expander tap area */
    .streamlit-expanderHeader {
        font-size: 1.05rem !important;
        padding: 0.7rem !important;
    }
    /* Cards look */
    .card {
        border: 1px solid #e5e7eb; 
        border-radius: 16px; 
        padding: 1rem;
        background-color: #ffffff;
        box-shadow: 0 1px 8px rgba(0,0,0,0.04);
    }
    </style>
    """,
    unsafe_allow_html=True,
)

PER_POINT_MULTIPLIER = 1.3162897354903684  # ~ +31.6% per "average factor" from precision-weighted regression
MAX_ABS_RISK = 0.95  # cap absolute risk to avoid nonsensical >100%

# Domain weights (integer points), built from your Cox HRs
# Hypertensive disorders are modeled as an ordinal domain (take the highest present)
HTN_LEVELS = [
    ("None", 0, "No chronic/gestational HTN, no edema/proteinuria codes"),
    ("Chronic HTN (I10)", 2, "Essential primary hypertension"),
    ("Gestational edema/proteinuria (O12)", 3, "Pregnancy-induced edema/proteinuria without HTN"),
    ("Gestational HTN (O13) or Unspecified HTN (O16)", 4, "Pregnancy-induced HTN w/o sig. proteinuria OR unspecified maternal HTN"),
]

# Other domains (additive)
DOMAINS = [
    ("Renal: CKD (N18)", 2, "Chronic kidney disease"),
    ("Multiple gestation (O30)", 2, "Any multiple gestation"),
    ("Placental pathology (O43 and/or O45)", 1, "Placental disorders and/or abruption"),
    ("Metabolic: Obesity (E66)", 1, "Overweight/obesity"),
    ("Metabolic: Diabetes in pregnancy (O24)", 1, "GDM/diabetes in pregnancy"),
    ("Autoimmune: SLE (M32)", 1, "Systemic lupus erythematosus"),
    ("Genetic/Screening: Abnormal antenatal screen (O28.5)", 1, "Abnormal chromosomal/genetic finding on maternal screen"),
    ("Demographics: Black or African American", 1, "Self-identified race"),
    ("Demographics: Hispanic or Latino", 1, "Self-identified ethnicity"),
]

CARE_PROCESS = [
    ("Care-process: Cesarean delivery w/o indication (O82)", 2, "Prediction-use only; may reflect downstream decisions"),
    ("Care-process: Supervision of high-risk pregnancy (O09)", 1, "Prediction-use only; care label"),
]

# -----------------------------
# Helpers
# -----------------------------
def rr_from_points(points: int) -> float:
    return PER_POINT_MULTIPLIER ** points

def absolute_risk(rr: float, baseline_risk: float) -> float:
    # Simple RR translation to absolute risk; cap to sane upper bound
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

def interpret_points_and_risk(total_points: int, rr: float, abs_risk: float) -> str:
    """Short, clinician-friendly interpretation string."""
    bucket = risk_bucket(rr)
    # Simple narrative based on point ranges users discussed (5–6 is a salient threshold)
    if total_points <= 2:
        nuance = "Risk elevation is modest; routine postpartum surveillance may suffice depending on clinical context."
    elif total_points <= 4:
        nuance = "Meaningful elevation; consider closer BP surveillance and symptom review consistent with local protocols."
    elif total_points <= 6:
        nuance = "Substantial elevation; aligns with the empiric 'higher-risk' zone in our data (≈4–5× baseline)."
    else:
        nuance = "Very substantial elevation; uncertainty may increase at extreme scores; emphasize follow-up reliability."
    return (
        f"**Category:** {bucket}\n\n"
        f"- **Score:** {total_points} points  \n"
        f"- **Relative risk:** {rr:.2f}× baseline  \n"
        f"- **Estimated absolute risk:** {pct(abs_risk)}  \n"
        f"- **Interpretation:** {nuance}"
    )

def clinician_note(patient_initials: str, total_points: int, rr: float, abs_risk: float, baseline_risk: float, htn_label: str, checked_domains: list, include_care: bool) -> str:
    today = dt.date.today().isoformat()
    domains_str = "; ".join(checked_domains) if checked_domains else "None selected"
    care_flag = "Included" if include_care else "Excluded"
    return (
        f"Postpartum Preeclampsia Risk Summary ({today})\n"
        f"Patient: {patient_initials or 'N/A'}\n"
        f"Score: {total_points} points | RR {rr:.2f}× vs baseline | Abs risk {pct(abs_risk)} (baseline {pct(baseline_risk)})\n"
        f"Hypertensive domain: {htn_label}\n"
        f"Other domains: {domains_str}\n"
        f"Care-process variables: {care_flag}\n"
        f"Method: Domain-weighted points mapped from multivariable Cox HRs; RR from 1.316^points; absolute risk = RR × baseline.\n"
        f"Note: For decision support only; interpret within clinical context and local guidance."
    )

# -----------------------------
# Sidebar: global settings
# -----------------------------
st.sidebar.header("Settings")

baseline_risk_pct = st.sidebar.number_input(
    "Baseline absolute risk (0-factor group, %)",
    min_value=0.1, max_value=20.0, value=3.8, step=0.1,
    help=(
        "Absolute risk (%) for patients with zero risk factors. "
        "Use your observed value from the 0-factor cohort. "
        "Default 3.8% reflects baseline percentages from your summaries."
    ),
)
baseline_risk = baseline_risk_pct / 100.0

include_care_process = st.sidebar.toggle(
    "Include care-process variables (prediction-only)?",
    value=False,
    help="If ON, O82 and O09 add points. For causal interpretation keep OFF; for prediction you may include."
)

st.sidebar.caption(
    "Per-point multiplier fixed at 1.316 (precision-weighted log-linear fit). "
    "Absolute risk = RR × baseline."
)

# -----------------------------
# Header
# -----------------------------
st.title("🩺 Postpartum Preeclampsia Risk Calculator")
st.caption(
    "Mobile-optimized, domain-weighted score derived from a multivariable Cox model and validated against an empirical factor–risk curve."
)

# -----------------------------
# Input form (mobile friendly)
# -----------------------------
with st.form("risk_form", clear_on_submit=False):
    st.subheader("Patient factors")

    # Hypertensive disorders (ordinal)
    st.markdown("**Hypertensive disorders (select highest applicable level):**")
    htn_level = st.radio(
        "Select the most severe applicable level",
        options=[lvl[0] for lvl in HTN_LEVELS],
        index=0,
        captions=[lvl[2] for lvl in HTN_LEVELS],
        horizontal=False,
        label_visibility="collapsed",
    )

    # Other domains
    st.markdown("**Other domains:**")
    domain_flags = {}
    for name, pts, hint in DOMAINS:
        domain_flags[name] = st.checkbox(name, help=hint)

    # Care-process (optional)
    if include_care_process:
        st.markdown("**Care-process variables (optional; prediction-only):**")
        for name, pts, hint in CARE_PROCESS:
            domain_flags[name] = st.checkbox(name, help=hint)

    st.markdown("---")
    patient_initials = st.text_input("Patient initials (optional, for note export)", value="", placeholder="AB, or leave blank")

    submitted = st.form_submit_button("Calculate risk", type="primary", use_container_width=True)

# -----------------------------
# Calculation
# -----------------------------
def compute_points(selected_htn_label: str, flags: dict, include_care: bool):
    # HTN points
    htn_points = get_htn_points(selected_htn_label)

    # Other domain points (additive)
    other_points = 0
    breakdown = []

    # Track selected domain names for export
    selected_names = []

    # HTN breakdown
    breakdown.append(("Hypertensive disorders", htn_points))

    # Add other domains
    for name, pts, _ in DOMAINS:
        if flags.get(name, False):
            other_points += pts
            breakdown.append((name, pts))
            selected_names.append(name)

    # Care-process
    if include_care:
        for name, pts, _ in CARE_PROCESS:
            if flags.get(name, False):
                other_points += pts
                breakdown.append((name, pts))
                selected_names.append(name)

    total = htn_points + other_points
    return total, breakdown, selected_names

if submitted:
    total_points, breakdown, selected_names = compute_points(htn_level, domain_flags, include_care_process)
    rr = rr_from_points(total_points)
    abs_risk = absolute_risk(rr, baseline_risk)
    bucket = risk_bucket(rr)

    st.success("Risk calculated")

    # ----- Result card -----
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.markdown("### Result")
    c1, c2, c3 = st.columns(3)
    with c1:
        st.metric("Total points", total_points)
    with c2:
        st.metric("Relative risk", f"{rr:.2f}×")
    with c3:
        st.metric("Estimated absolute risk", pct(abs_risk))
    st.markdown(
        f"**Risk category:** {bucket}  \n"
        f"Computed as **RR = 1.316^points** and **Absolute risk = RR × baseline ({pct(baseline_risk)})**."
    )
    st.markdown('</div>', unsafe_allow_html=True)

    # ----- Interpretation card -----
    st.markdown('<div class="card" style="margin-top: 0.75rem;">', unsafe_allow_html=True)
    st.markdown("### Interpretation")
    st.markdown(interpret_points_and_risk(total_points, rr, abs_risk))
    st.markdown(
        """
**Context & guidance (non-directive):**
- Hypertensive disorders weigh most heavily in the score; the HTN domain is **ordinal** (use highest level only).
- Scores **5–6** align with a **substantially elevated** risk zone in our data (≈4–5× baseline).
- Consider aligning surveillance and follow-up with **local protocols/ACOG guidance** and patient-specific factors.
- Tailor counseling with absolute risk (percentage) alongside the relative risk multiplier.
        """
    )
    st.markdown('</div>', unsafe_allow_html=True)

    # ----- Points breakdown -----
    with st.expander("Show points breakdown"):
        if breakdown:
            st.table(
                {"Domain / Factor": [b[0] for b in breakdown],
                 "Points": [b[1] for b in breakdown]}
            )
        else:
            st.write("No additional risk domains selected.")

    # ----- Downloadable clinician note -----
    note = clinician_note(
        patient_initials, total_points, rr, abs_risk, baseline_risk, htn_level, selected_names, include_care_process
    )
    st.download_button(
        "Download clinician note (.txt)",
        data=note.encode("utf-8"),
        file_name=f"PPE_risk_{patient_initials or 'patient'}_{dt.date.today().isoformat()}.txt",
        mime="text/plain",
        use_container_width=True
    )

# -----------------------------
# Footer
# -----------------------------
st.divider()
with st.expander("Model provenance"):
    st.caption(
        "Weights derived from a multivariable Cox model (dominant HRs for O12/O13/O16), "
        "mapped to integers via ln(HR) relative to the empiric per-factor multiplier (≈1.316). "
        "The factor–risk curve (precision-weighted regression) explained ~96–99.8% of log-risk variance; "
        "diminishing marginal increases beyond 5–6 points."
    )
st.caption("For decision support; not a substitute for clinical judgment.")
