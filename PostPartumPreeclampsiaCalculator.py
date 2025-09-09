import math
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


# -----------------------------
# Sidebar: global settings
# -----------------------------
st.sidebar.header("Settings")

baseline_risk_pct = st.sidebar.number_input(
    "Baseline absolute risk (0-factor group)",
    min_value=0.1, max_value=20.0, value=3.8, step=0.1,
    help=(
        "Absolute risk (%) for patients with zero risk factors. "
        "Use your observed value from the 0-factor cohort. "
        "Default 3.8% reflects the baseline percentages in your summaries."
    ),
)
baseline_risk = baseline_risk_pct / 100.0

include_care_process = st.sidebar.toggle(
    "Include care-process variables (prediction-only)?",
    value=False,
    help="If ON, O82 and O09 add points. For causal interpretation keep OFF; for prediction you may include."
)

st.sidebar.caption(
    "Per-point multiplier fixed at 1.316 (from precision-weighted log-linear fit). "
    "Absolute risk = RR × baseline."
)

# -----------------------------
# Header
# -----------------------------
st.title("🩺 Postpartum Preeclampsia Risk Calculator")
st.caption(
    "Domain-weighted score derived from a multivariable Cox model and validated against an empirical factor–risk curve. "
    "Designed for quick, mobile-friendly use."
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

    # Submit
    submitted = st.form_submit_button("Calculate risk", type="primary", use_container_width=True)

# -----------------------------
# Calculation
# -----------------------------
def compute_points():
    # HTN points
    htn_points = {lvl[0]: lvl[1]}.get(htn_level, 0)
    # Other domain points (additive)
    other_points = 0
    breakdown = []

    # HTN breakdown
    breakdown.append(("Hypertensive disorders", htn_points))

    # Add other domains
    for name, pts, _ in DOMAINS:
        if domain_flags.get(name, False):
            other_points += pts
            breakdown.append((name, pts))

    # Care-process
    if include_care_process:
        for name, pts, _ in CARE_PROCESS:
            if domain_flags.get(name, False):
                other_points += pts
                breakdown.append((name, pts))

    total = htn_points + other_points
    return total, breakdown

if submitted:
    total_points, breakdown = compute_points()
    rr = rr_from_points(total_points)
    abs_risk = absolute_risk(rr, baseline_risk)
    bucket = risk_bucket(rr)

    st.success("Risk calculated")

    # Summary card
    st.markdown("### Result")
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Total points", total_points)
    with col2:
        st.metric("Relative risk vs baseline", f"{rr:.2f}×")
    with col3:
        st.metric("Estimated absolute risk", pct(abs_risk))

    st.markdown(
        f"**Risk category:** {bucket}  \n"
        f"Computed as **RR = 1.316^points** and **Absolute risk = RR × baseline ({pct(baseline_risk)})**."
    )

    # Points breakdown
    with st.expander("Show points breakdown"):
        if breakdown:
            st.table(
                {"Domain / Factor": [b[0] for b in breakdown],
                 "Points": [b[1] for b in breakdown]}
            )
        else:
            st.write("No additional risk domains selected.")

    # Guidance
    st.markdown("### Interpretation & Notes")
    st.markdown(
        """
- **Hypertensive disorders** dominate risk; use the **highest** level only (ordinal domain prevents double-counting).
- **Care-process variables** (O82, O09) can be **included for prediction**, but avoid for causal interpretation.
- The **baseline risk** should be set to your observed incidence in the **0-factor cohort** to obtain calibrated absolute risks.
- Typical action threshold in our data: **5–6 points ≈ 4–5×** baseline risk.
        """
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
st.caption("© Your Team — For clinical decision support; not a substitute for clinical judgment.")

