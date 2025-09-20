# app.py
import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go

st.set_page_config(page_title="Lebanon Water — Springs & Sources", layout="wide")

# --------------------------
# 0) Column names (edit here if your headers differ)
# --------------------------
COL_GOV   = "GovernorateName"
COL_TOWN  = "Town"
COL_PERM  = "Total number of permanent water springs"
COL_SEAS  = "Total number of seasonal water springs"

COL_PUBLIC = "Public network"
COL_WELL   = "Artesian well"
COL_GALLON = "Gallons purchase"
COL_POINT  = "Water point"
COL_OTHER  = "Other"

WATER_SRC_COLS = [COL_PUBLIC, COL_WELL, COL_GALLON, COL_POINT, COL_OTHER]

# --------------------------
# 1) Data loading
# --------------------------
@st.cache_data
def load_csv(file):
    df = pd.read_csv(file)
    return df

st.title("Lebanon Water — Springs & Sources")

st.markdown(
    "Explore permanent vs. seasonal springs and potable water sources by governorate. "
    "**Use the filters in the sidebar** to change what you see."
)

file = st.sidebar.file_uploader("water_resources.csv", type=["csv"])
if file is None:
    st.sidebar.info("No file uploaded — I'll try to read `water_resources.csv` in the app folder.")
    try:
        df = load_csv("water_resources.csv")
    except Exception as e:
        st.error("Could not load data. Upload your CSV or place `water_resources.csv` beside app.py.")
        st.stop()
else:
    df = load_csv(file)

# Coerce numeric cols we need
for c in [COL_PERM, COL_SEAS] + WATER_SRC_COLS:
    if c in df.columns:
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)

# --------------------------
# 2) Sidebar interactions (TWO main controls)
# --------------------------
# (A) Governorate filter
govs_all = sorted([g for g in df[COL_GOV].dropna().unique()])
gov_select = st.sidebar.multiselect("Governorates", govs_all, default=govs_all)

# (B) Value mode
mode = st.sidebar.radio(
    "Value mode",
    ["Absolute", "Normalized"],
    index=0,
    help=(
        "Absolute: totals.  Normalized: "
        "Springs = per-town average; Heatmap = share % within governorate."
    )
)

# Filter data
d = df[df[COL_GOV].isin(gov_select)].copy()
if d.empty:
    st.warning("No rows after filtering. Pick at least one governorate.")
    st.stop()

# --------------------------
# 3) LEFT: Pyramid — Permanent vs Seasonal springs
# --------------------------
st.markdown("### Permanent vs Seasonal Springs by Governorate")

# Aggregate
spr = (
    d.dropna(subset=[COL_GOV])
     .groupby(COL_GOV, as_index=False)[[COL_PERM, COL_SEAS]]
     .sum()
)

# Sorting by total so the largest shows near the top visually
spr["Total"] = spr[COL_PERM] + spr[COL_SEAS]
spr = spr.sort_values("Total", ascending=True)

# Normalize option (per-town average)
if mode == "Normalized":
    towns = (
        d.dropna(subset=[COL_GOV, COL_TOWN])
         .groupby(COL_GOV, as_index=False)[COL_TOWN].nunique()
         .rename(columns={COL_TOWN: "Towns"})
    )
    spr = spr.merge(towns, on=COL_GOV, how="left")
    spr["Towns"] = spr["Towns"].replace(0, np.nan)
    spr[COL_PERM] = (spr[COL_PERM] / spr["Towns"]).round(2)
    spr[COL_SEAS] = (spr[COL_SEAS] / spr["Towns"]).round(2)
    y_axis_title = "Avg springs per town"
else:
    y_axis_title = "Number of springs"

govs = spr[COL_GOV].tolist()
perm = spr[COL_PERM].to_numpy()
seas = spr[COL_SEAS].to_numpy()

# Dynamic symmetric axis
max_abs = int(np.ceil(max(float(np.max(perm or [0])), float(np.max(seas or [0]))) / 50.0)) * 50 or 50
step    = max(50, max_abs // 5)
tickvals = list(range(-max_abs, max_abs + step, step))
ticktext = [str(abs(v)) for v in tickvals]

blue_dark   = "#08306B"
blue_medium = "#6BAED6"

fig_pyr = go.Figure()
# Left (negative) — Permanent
fig_pyr.add_trace(go.Bar(
    x=-perm, y=govs, orientation="h",
    name="Permanent (left)",
    marker_color=blue_dark,
    text=[f"{v:,.2f}" if mode=="Normalized" else f"{int(v):,}" for v in perm],
    textposition="outside",
    cliponaxis=False
))
# Right (positive) — Seasonal
fig_pyr.add_trace(go.Bar(
    x=seas, y=govs, orientation="h",
    name="Seasonal (right)",
    marker_color=blue_medium,
    text=[f"{v:,.2f}" if mode=="Normalized" else f"{int(v):,}" for v in seas],
    textposition="outside",
    cliponaxis=False
))

fig_pyr.update_layout(
    template="plotly_white",
    barmode="overlay", bargap=0.2,
    xaxis=dict(
        title=y_axis_title,
        range=[-max_abs, max_abs],
        tickmode="array", tickvals=tickvals, ticktext=ticktext,
        zeroline=True, zerolinewidth=2, zerolinecolor="rgba(0,0,0,0.35)"
    ),
    yaxis=dict(title="Governorate"),
    legend=dict(orientation="h", y=1.06, x=0),
    margin=dict(l=90, r=40, t=10, b=40)
)
fig_pyr.update_traces(marker_line_color="white", marker_line_width=0.8)
st.plotly_chart(fig_pyr, use_container_width=True)

# Quick insight below the chart (auto)
gap = (spr[COL_SEAS] - spr[COL_PERM]).sort_values(ascending=False)
top_g = gap.index[0]
st.caption(
    f"**Insight:** Seasonal exceeds permanent most in **{spr.loc[top_g, COL_GOV]}** "
    f"(Δ = {gap.iloc[0]:.2f}{' avg/town' if mode=='Normalized' else ''})."
)

# --------------------------
# 4) RIGHT: Heatmap — Water source mix
# --------------------------
st.markdown("### Potable Water Source Mix by Governorate")

src = (
    d.dropna(subset=[COL_GOV])
     .groupby(COL_GOV, as_index=False)[WATER_SRC_COLS]
     .sum()
)

if mode == "Normalized":
    vals = src[WATER_SRC_COLS].astype(float)
    src_sum = vals.sum(axis=1).replace(0, np.nan)
    heat = (vals.div(src_sum, axis=0) * 100).round(1)
    cbar_title = "Share (%)"
    text_auto  = True
else:
    heat = src[WATER_SRC_COLS].round(0)
    cbar_title = "Total count"
    text_auto  = True

heat.index = src[COL_GOV]
heat.columns = ["Public network", "Artesian well", "Gallons", "Water point", "Other"]

fig_heat = px.imshow(
    heat,
    text_auto=text_auto,
    color_continuous_scale=px.colors.sequential.Blues,
    aspect="auto",
    labels=dict(x="Source", y="Governorate", color=cbar_title),
)
fig_heat.update_layout(template="plotly_white", margin=dict(l=10, r=10, t=10, b=10))
st.plotly_chart(fig_heat, use_container_width=True)

# Short takeaway for the heatmap
if mode == "Normalized":
    top_pub = heat["Public network"].sort_values(ascending=False).index[0]
    st.caption(f"**Note:** In normalized mode, **{top_pub}** shows the highest reliance on the public network.")
else:
    top_abs = heat["Public network"].sort_values(ascending=False).index[0]
    st.caption(f"**Note:** In absolute mode, **{top_abs}** has the largest count of households using the public network.")

# --------------------------
# 5) Context & how to read this page
# --------------------------
with st.expander("What am I looking at? (Context & How to read)"):
    st.markdown(
        """
- **Left chart (Pyramid):** compares **permanent** (left) vs **seasonal** (right) springs by governorate.
  - Switch **Value mode** to *Normalized* for **per-town averages** (fair across different numbers of towns).
- **Right chart (Heatmap):** shows the **mix of water sources** by governorate.
  - In *Normalized* mode it shows **shares (%)**; in *Absolute* it shows **totals**.
- **Governorate filter** applies to both plots.
        """
    )

st.success("✅ Page includes 2 interactive features: Governorate filter + Value mode switch that changes the data shown.")

# --------------------------
# Footer / deployment hint
# --------------------------
st.markdown("---")
st.subheader("How to publish (Streamlit Cloud)")
st.markdown(
    """
1. Put `app.py` and your CSV in a GitHub repo.  
2. Create a free account at [share.streamlit.io](https://share.streamlit.io) and deploy the repo.  
3. In the app settings, set the **entry point** to `app.py`.  
4. After it builds, copy the **public URL** and submit it for your assignment.
"""
)
