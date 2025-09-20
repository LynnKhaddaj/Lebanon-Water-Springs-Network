# app.py
import re
import numpy as np
import pandas as pd
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go

# ----------------------------
# Page setup
# ----------------------------
st.set_page_config(page_title="Lebanon Water — Springs & Sources", layout="wide")
st.title("Lebanon Water — Springs & Sources")
st.markdown(
    "Explore **permanent vs. seasonal springs** and the **mix of potable water sources** by governorate. "
    "Use the **filters in the sidebar** to change what you see."
)

# ----------------------------
# Load data
# ----------------------------
@st.cache_data
def load_csv_from_path(path: str) -> pd.DataFrame:
    return pd.read_csv(path)

uploaded = st.sidebar.file_uploader("Upload CSV (water_resources.csv)", type=["csv"])
if uploaded is not None:
    df = load_csv_from_path(uploaded)
else:
    st.sidebar.info("No file uploaded — trying to read `water_resources.csv` from the repo.")
    try:
        df = load_csv_from_path("water_resources.csv")
    except Exception:
        st.error("Could not load data. Upload your CSV or add `water_resources.csv` beside app.py.")
        st.stop()

# ----------------------------
# Light cleaning & flexible columns
# ----------------------------
df.columns = [c.strip() for c in df.columns]

def parse_ref_area(s: str):
    """Return (AreaName, AreaType) from strings like 'Akkar_Governorate' / 'Zahle_District'."""
    if not isinstance(s, str):
        return (np.nan, "Other")
    m = re.match(r"^(.*)_(Governorate|District)$", s.strip())
    if m:
        nm, t = m.groups()
        return (nm.replace("_", " ").strip(), t)
    return (s.replace("_", " ").strip(), "Other")

# If GovernorateName is missing, try to derive from refArea
if "GovernorateName" not in df.columns:
    if "refArea" in df.columns:
        area_parsed = df["refArea"].apply(parse_ref_area)
        df["AreaName"], df["AreaType"] = zip(*area_parsed)
        df["GovernorateName"] = np.where(df["AreaType"] == "Governorate", df["AreaName"], np.nan)
        df["DistrictName"]    = np.where(df["AreaType"] == "District",     df["AreaName"], np.nan)
    else:
        st.error("Missing `GovernorateName` and `refArea`. I can't determine geography.")
        st.stop()

# Tidy Town if present
HAS_TOWN = "Town" in df.columns
if HAS_TOWN:
    df["Town"] = (
        df["Town"].astype(str)
        .str.strip()
        .str.replace(r"\s+", " ", regex=True)
    )

# Normalize a few governorate names
gov_std = {"North": "North Lebanon", "South": "South Lebanon", "Beqaa": "Bekaa"}
df["GovernorateName"] = df["GovernorateName"].replace(gov_std)

def first_present(frame: pd.DataFrame, *cands):
    for c in cands:
        if c in frame.columns:
            return c
    return None

# Springs (required)
COL_SPRING_PERM = first_present(
    df, "Total number of permanent water springs", "Permanent springs", "Permanent"
)
COL_SPRING_SEAS = first_present(
    df, "Total number of seasonal water springs", "Seasonal springs", "Seasonal"
)
if not COL_SPRING_PERM or not COL_SPRING_SEAS:
    st.error("Missing spring columns (permanent/seasonal).")
    st.stop()

# Water source (optional for heatmap)
COL_PUBLIC  = first_present(df, "Public network",  "Potable water source - public network")
COL_WELL    = first_present(df, "Artesian well",   "Potable water source - artesian well")
COL_GALLONS = first_present(df, "Gallons purchase","Potable water source - gallons purchase")
COL_POINT   = first_present(df, "Water point",     "Potable water source - water point")
COL_OTHER   = first_present(df, "Other",           "Potable water source - other")
WATER_SRC_COLS = [c for c in [COL_PUBLIC, COL_WELL, COL_GALLONS, COL_POINT, COL_OTHER] if c]

# Coerce numerics where relevant
for c in [COL_SPRING_PERM, COL_SPRING_SEAS] + WATER_SRC_COLS:
    if c:
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)

if len(WATER_SRC_COLS) < 2:
    st.info("Water-source columns are incomplete in this CSV — the heatmap may be limited.")

# ----------------------------
# Sidebar interactions
# ----------------------------
govs_all = sorted([g for g in df["GovernorateName"].dropna().unique()])
gov_select = st.sidebar.multiselect("Governorates", govs_all, default=govs_all)

mode = st.sidebar.radio(
    "Value mode",
    ["Absolute totals", "Normalized"],
    index=0,
    help=(
        "Absolute: totals.  Normalized: "
        "Springs = per-town average; Heatmap = share % within governorate."
    ),
)

# If user picks Normalized but we don't have Town, fall back gracefully
if mode == "Normalized" and not HAS_TOWN:
    st.sidebar.warning("No `Town` column — Normalized mode for springs will use totals.")
    springs_normalized = False
else:
    springs_normalized = (mode == "Normalized")

data = df[df["GovernorateName"].isin(gov_select)].copy()
if data.empty:
    st.warning("No data after filtering. Pick at least one governorate.")
    st.stop()

# ----------------------------
# Viz 1: Pyramid — Permanent vs Seasonal springs
# ----------------------------
st.subheader("Permanent vs Seasonal Springs by Governorate")

spr = (
    data.dropna(subset=["GovernorateName"])
        .groupby("GovernorateName", as_index=False)[[COL_SPRING_PERM, COL_SPRING_SEAS]]
        .sum()
)

# Sorting so larger totals end up visually near the top
spr["Total"] = spr[COL_SPRING_PERM] + spr[COL_SPRING_SEAS]
spr = spr.sort_values("Total", ascending=True)

if springs_normalized:
    towns = (
        data.dropna(subset=["GovernorateName"])
            .groupby("GovernorateName", as_index=False)["Town"].nunique()
            .rename(columns={"Town": "Towns"})
    )
    spr = spr.merge(towns, on="GovernorateName", how="left")
    spr["Towns"] = spr["Towns"].replace(0, np.nan)
    spr[COL_SPRING_PERM] = (spr[COL_SPRING_PERM] / spr["Towns"]).round(2)
    spr[COL_SPRING_SEAS] = (spr[COL_SPRING_SEAS] / spr["Towns"]).round(2)
    x_title = "Avg springs per town"
else:
    x_title = "Number of springs"

govs = spr["GovernorateName"].tolist()
perm = spr[COL_SPRING_PERM].to_numpy()
seas = spr[COL_SPRING_SEAS].to_numpy()

# dynamic symmetric axis
max_abs_val = float(max(perm.max() if len(perm) else 0, seas.max() if len(seas) else 0))
max_abs = int(np.ceil(max_abs_val / 50.0)) * 50 or 50
step    = max(50, max_abs // 5)
tickvals = list(range(-max_abs, max_abs + step, step))
ticktext = [str(abs(v)) for v in tickvals]

blue_dark   = "#08306B"
blue_medium = "#6BAED6"

fig_pyr = go.Figure()
fig_pyr.add_trace(go.Bar(
    x=-perm, y=govs, orientation="h",
    name="Permanent (left)", marker_color=blue_dark,
    text=[f"{v:,.2f}" if springs_normalized else f"{int(v):,}" for v in perm],
    textposition="outside", cliponaxis=False
))
fig_pyr.add_trace(go.Bar(
    x=seas, y=govs, orientation="h",
    name="Seasonal (right)", marker_color=blue_medium,
    text=[f"{v:,.2f}" if springs_normalized else f"{int(v):,}" for v in seas],
    textposition="outside", cliponaxis=False
))
fig_pyr.update_traces(marker_line_color="white", marker_line_width=0.8)
fig_pyr.update_layout(
    template="plotly_white", barmode="overlay", bargap=0.2,
    xaxis=dict(
        title=x_title, range=[-max_abs, max_abs],
        tickmode="array", tickvals=tickvals, ticktext=ticktext,
        zeroline=True, zerolinewidth=2, zerolinecolor="rgba(0,0,0,0.35)"
    ),
    yaxis=dict(title="Governorate"),
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
    margin=dict(l=100, r=40, t=20, b=50)
)
st.plotly_chart(fig_pyr, use_container_width=True)

# quick insight
gap = (spr[COL_SPRING_SEAS] - spr[COL_SPRING_PERM])
max_idx = gap.idxmax()
st.caption(
    f"**Insight:** Seasonal exceeds permanent most in **{spr.loc[max_idx, 'GovernorateName']}** "
    f"(Δ = {gap.loc[max_idx]:.2f}{' avg/town' if springs_normalized else ''})."
)

# ----------------------------
# Viz 2: Heatmap — Potable water source mix
# ----------------------------
st.subheader("Potable Water Source Mix by Governorate")

if len(WATER_SRC_COLS) >= 2:
    src = (
        data.dropna(subset=["GovernorateName"])
            .groupby("GovernorateName", as_index=False)[WATER_SRC_COLS]
            .sum()
    )

    if mode == "Normalized":
        vals = src[WATER_SRC_COLS].astype(float)
        row_sum = vals.sum(axis=1).replace(0, np.nan)
        heat = (vals.div(row_sum, axis=0) * 100).round(1)
        cbar_title = "Share (%)"
        text_auto = True
    else:
        heat = src[WATER_SRC_COLS].round(0)
        cbar_title = "Total count"
        text_auto = True

    # Human-friendly column order/names if possible
    rename_nice = {
        COL_PUBLIC: "Public network",
        COL_WELL: "Artesian well",
        COL_GALLONS: "Gallons",
        COL_POINT: "Water point",
        COL_OTHER: "Other",
    }
    heat = heat.rename(columns={k: v for k, v in rename_nice.items() if k in heat.columns})
    heat.index = src["GovernorateName"]

    fig_heat = px.imshow(
        heat,
        text_auto=text_auto,
        color_continuous_scale=px.colors.sequential.Blues,
        aspect="auto",
        labels=dict(x="Source", y="Governorate", color=cbar_title),
    )
    fig_heat.update_layout(template="plotly_white", margin=dict(l=10, r=10, t=10, b=10))
    st.plotly_chart(fig_heat, use_container_width=True)

    if mode == "Normalized" and "Public network" in heat.columns:
        top_pub = heat["Public network"].sort_values(ascending=False).index[0]
        st.caption(f"**Note:** In normalized mode, **{top_pub}** shows the highest public-network share.")
else:
    st.info("Not enough water-source columns to draw the heatmap.")

# ----------------------------
# Context / help
# ----------------------------
with st.expander("What am I looking at?"):
    st.markdown(
        """
- **Pyramid chart**: compares **permanent** (left) vs **seasonal** (right) springs.  
  Switch **Value mode** to *Normalized* for **per-town averages** (fairer across places with more towns).
- **Heatmap**: shows the **mix of potable water sources** by governorate.  
  In *Normalized* it shows **within-governorate shares**; in *Absolute* it shows **totals**.
- The **Governorate filter** applies to all visuals.
        """
    )

st.success("✅ Interactions wired: Governorate filter + Value mode switch (changes the data/plots).")


