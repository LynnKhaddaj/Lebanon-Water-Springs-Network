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
st.set_page_config(page_title="Lebanon Water — Springs & Network", layout="wide")
st.title("Lebanon Water — Springs & Network")
st.caption("Filter, aggregate, and rank areas to explore seasonal dependence and network condition.")

# ----------------------------
# Load data (no uploader)
# ----------------------------
@st.cache_data
def load_csv(path: str) -> pd.DataFrame:
    return pd.read_csv(path)

try:
    df = load_csv("water_resources.csv")
except Exception:
    st.error("Could not load `water_resources.csv`. Make sure it sits next to `app.py` in your repo.")
    st.stop()

df.columns = [c.strip() for c in df.columns]

# ----------------------------
# Flexible columns & light cleaning
# ----------------------------
def parse_ref_area(s: str):
    if not isinstance(s, str):
        return (np.nan, "Other")
    m = re.match(r"^(.*)_(Governorate|District)$", s.strip())
    if m:
        name_raw, a_type = m.groups()
        return (name_raw.replace("_", " ").strip(), a_type)
    return (s.replace("_", " ").strip(), "Other")

# If GovernorateName missing, derive from refArea
if "GovernorateName" not in df.columns:
    if "refArea" in df.columns:
        area_parsed = df["refArea"].apply(parse_ref_area)
        df["AreaName"], df["AreaType"] = zip(*area_parsed)
        df["GovernorateName"] = np.where(df["AreaType"] == "Governorate", df["AreaName"], np.nan)
        df["DistrictName"]    = np.where(df["AreaType"] == "District",     df["AreaName"], np.nan)
    else:
        st.error("Missing `GovernorateName` and `refArea` — cannot determine geography.")
        st.stop()

HAS_TOWN = "Town" in df.columns
if HAS_TOWN:
    df["Town"] = (
        df["Town"].astype(str).str.strip().str.replace(r"\s+", " ", regex=True)
    )

# Normalize a few governorate spellings
gov_std = {"North": "North Lebanon", "South": "South Lebanon", "Beqaa": "Bekaa"}
df["GovernorateName"] = df["GovernorateName"].replace(gov_std)

def first_present(frame: pd.DataFrame, *cands):
    for c in cands:
        if c in frame.columns:
            return c
    return None

# Required: springs
COL_SPRING_PERM = first_present(
    df, "Total number of permanent water springs", "Permanent springs", "Permanent"
)
COL_SPRING_SEAS = first_present(
    df, "Total number of seasonal water springs", "Seasonal springs", "Seasonal"
)
if not COL_SPRING_PERM or not COL_SPRING_SEAS:
    st.error("Missing spring columns (permanent/seasonal).")
    st.stop()

# Optional: network condition
COL_STATE_GOOD = first_present(df, "State of the water network - good", "Good %", "Good")
COL_STATE_ACC  = first_present(df, "State of the water network - acceptable", "Acceptable %", "Acceptable")
COL_STATE_BAD  = first_present(df, "State of the water network - bad", "Bad %", "Bad")

for c in [COL_SPRING_PERM, COL_SPRING_SEAS, COL_STATE_GOOD, COL_STATE_ACC, COL_STATE_BAD]:
    if c and c in df.columns:
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)

# ----------------------------
# Sidebar interactions
# ----------------------------
st.sidebar.header("Filters")

# (1) Aggregate by Governorate vs District
group_level = st.sidebar.radio(
    "Aggregate by",
    ["Governorate", "District"],
    index=0,
    help="Changes the level at which data is aggregated for both charts."
)
if group_level == "District" and "DistrictName" not in df.columns:
    st.sidebar.warning("No DistrictName column in this CSV — falling back to Governorate.")
    group_level = "Governorate"
GROUP_COL = "GovernorateName" if group_level == "Governorate" else "DistrictName"

# (2) Area profile filter (external classification: Urban / Agriculture / Mixed)
# Governorate tags
GOV_TAG = {
    # Urban-dense / city-like
    "Beirut": "Urban",
    "Mount Lebanon": "Urban",
    "Keserwan-Jbeil": "Urban",  # if present in your admin layer

    # Agriculture/Rural-dominant
    "Bekaa": "Agriculture",
    "Baalbek-El Hermel": "Agriculture",
    "El Nabatieh": "Agriculture",
    "Akkar": "Agriculture",

    # Mixed
    "North": "Mixed",
    "South": "Mixed",
}
# District tags (practical starting point; adjust spellings to your data if needed)
DIST_TAG = {
    # Urban / city-like cores
    "Tripoli": "Urban",
    "Saida": "Urban",
    "Sour": "Urban", "Tyre": "Urban",
    "Baabda": "Urban",
    "El Metn": "Urban", "Metn": "Urban",
    "Aley": "Urban",
    "Kesrouan": "Urban", "Keserwan": "Urban",
    "Chouf": "Urban", "Shouf": "Urban",
    "Jbail": "Urban", "Byblos": "Urban",

    # Agriculture / Rural
    "Akkar": "Agriculture",
    "Baalbek": "Agriculture",
    "Hermel": "Agriculture",
    "Zahleh": "Agriculture", "Zahle": "Agriculture",
    "West Bekaa": "Agriculture",
    "Rachaya": "Agriculture",
    "Bint Jbeil": "Agriculture",
    "Marjaayoun": "Agriculture", "Marjeyoun": "Agriculture",
    "Hasbaya": "Agriculture",
    "Jezzine": "Agriculture",
    "Minieh-Dinnieh": "Agriculture", "Miniyeh-Danniyeh": "Agriculture",
    "Bcharre": "Agriculture",
    "Koura": "Agriculture",
    "Batroun": "Agriculture",
    "Zgharta": "Agriculture",
}

def area_tag_from_row(row):
    if GROUP_COL == "GovernorateName":
        return GOV_TAG.get(str(row["GovernorateName"]).strip(), "Mixed")
    else:
        return DIST_TAG.get(str(row["DistrictName"]).strip(), "Agriculture")

df["AreaTagExternal"] = df.apply(area_tag_from_row, axis=1)

area_choice = st.sidebar.radio(
    "Area profile (external)",
    ["All areas", "Urban only", "Agriculture/Rural only", "Mixed only"],
    index=0,
    help="Subsets rows before aggregation using an external Urban/Agriculture/Mixed mapping."
)

# Subset the data by area profile before listing choices
data0 = df.copy()
if area_choice != "All areas":
    keep = {
        "Urban only": "Urban",
        "Agriculture/Rural only": "Agriculture",
        "Mixed only": "Mixed",
    }[area_choice]
    data0 = data0[data0["AreaTagExternal"] == keep]

# Area selector (based on filtered rows)
areas_all = sorted(data0[GROUP_COL].dropna().unique().tolist())
pick_areas = st.sidebar.multiselect(f"{group_level}s", areas_all, default=areas_all)

# Springs scale (Totals vs per-town)
display_mode = st.sidebar.radio(
    "Springs scale",
    ["Totals", "Per-town average"],
    index=0,
    help="Per-town average divides by the number of unique towns per selected area."
)

st.sidebar.markdown("---")
st.sidebar.subheader("Pyramid sorting")
sort_opt = st.sidebar.selectbox(
    "Sort by",
    [
        "Total springs",
        "Seasonal − Permanent (gap)",
        "Seasonal / Permanent (ratio)",
        "Seasonal only",
        "Permanent only",
    ],
    index=1,
)
ascending = st.sidebar.checkbox("Ascending order", value=False)
max_n_now = max(1, len(areas_all))
top_n_pyr = st.sidebar.slider("Show top-N areas (after sort)", 1, max_n_now, min(8, max_n_now))

st.sidebar.markdown("---")
st.sidebar.subheader("Network sorting")
net_sort_opt = st.sidebar.selectbox(
    "Sort by",
    ["Good %", "Bad %", "Acceptable %"],
    index=0,
)
net_ascending = st.sidebar.checkbox("Ascending", value=False, key="net_asc")
top_n_net = st.sidebar.slider("Show top-N areas", 1, max_n_now, min(8, max_n_now), key="net_n")
show_labels_net = st.sidebar.checkbox("Show labels on bars", value=True)

# Final filtered data by area selection
data = data0[data0[GROUP_COL].isin(pick_areas)].copy()
if data.empty:
    st.warning("No rows after the chosen filters. Select different filters/areas.")
    st.stop()

# ----------------------------
# Viz 1: Pyramid — Permanent vs Seasonal (by GROUP_COL)
# ----------------------------
st.subheader(f"Permanent vs Seasonal Springs by {group_level}")

spr = (
    data.groupby(GROUP_COL, as_index=False)[[COL_SPRING_PERM, COL_SPRING_SEAS]].sum()
)

if display_mode == "Per-town average" and HAS_TOWN:
    town_counts = data.groupby(GROUP_COL, as_index=False)["Town"].nunique().rename(columns={"Town":"Towns"})
    spr = spr.merge(town_counts, on=GROUP_COL, how="left")
    spr["Towns"] = spr["Towns"].replace(0, np.nan)
    spr[COL_SPRING_PERM] = (spr[COL_SPRING_PERM] / spr["Towns"]).round(2)
    spr[COL_SPRING_SEAS] = (spr[COL_SPRING_SEAS] / spr["Towns"]).round(2)
    x_title = "Avg springs per town"
else:
    x_title = "Number of springs"

# Sorting metric
spr["Total"] = spr[COL_SPRING_PERM] + spr[COL_SPRING_SEAS]
spr["Gap"]   = spr[COL_SPRING_SEAS] - spr[COL_SPRING_PERM]
spr["Ratio"] = np.where(spr[COL_SPRING_PERM] > 0, spr[COL_SPRING_SEAS] / spr[COL_SPRING_PERM], np.nan)

if sort_opt == "Total springs":
    spr = spr.sort_values("Total", ascending=ascending)
elif sort_opt == "Seasonal − Permanent (gap)":
    spr = spr.sort_values("Gap", ascending=ascending)
elif sort_opt == "Seasonal / Permanent (ratio)":
    spr = spr.sort_values("Ratio", ascending=ascending)
elif sort_opt == "Seasonal only":
    spr = spr.sort_values(COL_SPRING_SEAS, ascending=ascending)
elif sort_opt == "Permanent only":
    spr = spr.sort_values(COL_SPRING_PERM, ascending=ascending)

# top-N after sort
spr = spr.tail(top_n_pyr)
areas = spr[GROUP_COL].tolist()
perm = spr[COL_SPRING_PERM].to_numpy()
seas = spr[COL_SPRING_SEAS].to_numpy()

max_abs_val = float(max(perm.max() if len(perm) else 0, seas.max() if len(seas) else 0))
step_base = 50 if display_mode == "Totals" else 1
max_abs = int(np.ceil(max_abs_val / step_base) * step_base) or step_base
step    = max(step_base, max_abs // 5)
tickvals = list(range(-max_abs, max_abs + step, step))
ticktext = [str(abs(v)) for v in tickvals]

blue_dark   = "#08306B"
blue_medium = "#6BAED6"

fig_pyr = go.Figure()
fig_pyr.add_trace(go.Bar(
    x=-perm, y=areas, orientation="h",
    name="Permanent (left)", marker_color=blue_dark,
    text=[f"{v:,.2f}" if display_mode!="Totals" else f"{int(v):,}" for v in perm],
    textposition="outside", cliponaxis=False
))
fig_pyr.add_trace(go.Bar(
    x=seas, y=areas, orientation="h",
    name="Seasonal (right)", marker_color=blue_medium,
    text=[f"{v:,.2f}" if display_mode!="Totals" else f"{int(v):,}" for v in seas],
    textposition="outside", cliponaxis=False
))
fig_pyr.update_traces(marker_line_color="white", marker_line_width=0.8)
fig_pyr.update_layout(
    template="plotly_white", barmode="overlay", bargap=0.25,
    xaxis=dict(
        title=x_title, range=[-max_abs, max_abs],
        tickmode="array", tickvals=tickvals, ticktext=ticktext,
        zeroline=True, zerolinewidth=2, zerolinecolor="rgba(0,0,0,0.35)"
    ),
    yaxis=dict(title=group_level),
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
    margin=dict(l=110, r=40, t=20, b=50)
)
st.plotly_chart(fig_pyr, use_container_width=True)

# One-sentence takeaway
gap = spr["Gap"]
max_idx = gap.idxmax()
st.caption(
    f"**Largest seasonal dependence:** {spr.loc[max_idx, GROUP_COL]} "
    f"(gap = {gap.loc[max_idx]:.2f}{' avg/town' if display_mode!='Totals' else ''})."
)

# ----------------------------
# Viz 2: Network condition — 100% stacked bar (by GROUP_COL)
# ----------------------------
st.subheader(f"State of Water Network by {group_level} (100% Stacked)")

if COL_STATE_GOOD and COL_STATE_ACC and COL_STATE_BAD:
    net = (
        data.groupby(GROUP_COL, as_index=False)[[COL_STATE_GOOD, COL_STATE_ACC, COL_STATE_BAD]].sum()
    )

    vals = net[[COL_STATE_GOOD, COL_STATE_ACC, COL_STATE_BAD]].astype(float)
    row_sum = vals.sum(axis=1).replace(0, np.nan)
    net_pct = (vals.div(row_sum, axis=0) * 100).round(1)

    net_pct[GROUP_COL] = net[GROUP_COL]

    # Sorting for network chart
    sort_key_map = {
        "Good %": COL_STATE_GOOD,
        "Bad %":  COL_STATE_BAD,
        "Acceptable %": COL_STATE_ACC,
    }
    net_pct = net_pct.sort_values(sort_key_map[net_sort_opt], ascending=net_ascending)
    net_pct = net_pct.tail(top_n_net)

    nice = {COL_STATE_GOOD: "Good %", COL_STATE_ACC: "Acceptable %", COL_STATE_BAD: "Bad %"}
    net_pct = net_pct.rename(columns=nice)

    net_long = net_pct.melt(
        id_vars=GROUP_COL,
        value_vars=["Good %", "Acceptable %", "Bad %"],
        var_name="Condition", value_name="Share"
    )

    fig_net = px.bar(
        net_long, x="Share", y=GROUP_COL,
        color="Condition", orientation="h",
        color_discrete_map={
            "Good %": "#2ECC71",       # green
            "Acceptable %": "#F1C40F", # yellow
            "Bad %": "#E74C3C",        # red
        },
        category_orders={"Condition": ["Good %", "Acceptable %", "Bad %"]},
        text="Share" if show_labels_net else None
    )
    fig_net.update_layout(
        template="plotly_white",
        xaxis=dict(title="Share (%)", range=[0, 100]),
        yaxis=dict(title=group_level),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        margin=dict(l=110, r=40, t=20, b=50)
    )
    if show_labels_net:
        fig_net.update_traces(texttemplate="%{text:.0f}%", textposition="outside", cliponaxis=False)
    st.plotly_chart(fig_net, use_container_width=True)

    st.caption("Tip: Sort by **Good %** to see strongest performers, or by **Bad %** to surface where the network struggles.")
else:
    st.info("Network condition columns not found — this chart is disabled for this CSV.")

st.success("✅ Interactions wired: Group-by (Governorate/District) + Area profile (Urban/Agriculture/Mixed) + Springs scale (Totals/Per-town).")



