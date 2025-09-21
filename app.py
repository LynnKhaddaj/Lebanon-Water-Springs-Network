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

# If GovernorateName/DistrictName missing, derive from refArea
if "GovernorateName" not in df.columns or "DistrictName" not in df.columns:
    if "refArea" in df.columns:
        area_parsed = df["refArea"].apply(parse_ref_area)
        df["AreaName"], df["AreaType"] = zip(*area_parsed)
        if "GovernorateName" not in df.columns:
            df["GovernorateName"] = np.nan
        if "DistrictName" not in df.columns:
            df["DistrictName"] = np.nan
        df.loc[df["AreaType"] == "Governorate", "GovernorateName"] = df.loc[df["AreaType"] == "Governorate", "AreaName"]
        df.loc[df["AreaType"] == "District", "DistrictName"] = df.loc[df["AreaType"] == "District", "AreaName"]
    else:
        st.error("Missing `GovernorateName`/`DistrictName` and `refArea` — cannot determine geography.")
        st.stop()

HAS_TOWN = "Town" in df.columns
if HAS_TOWN:
    df["Town"] = df["Town"].astype(str).str.strip().str.replace(r"\s+", " ", regex=True)

# Normalize a few governorate spellings
gov_std = {"North": "North Lebanon", "South": "South Lebanon", "Beqaa": "Bekaa"}
df["GovernorateName"] = df["GovernorateName"].replace(gov_std)

# ---- District aliases (force a single, clean name) ----
TARGET_MINIEH = "Minieh - Danniyeh"
DISTRICT_ALIASES = {
    "MiniyehâDanniyeh": TARGET_MINIEH,  # en dash
    "Miniyeh—Danniyeh": TARGET_MINIEH,    # em dash
    "Minieh-Danniyeh": TARGET_MINIEH,
    "MiniyehÃ¢Â€Â“Danniyeh": TARGET_MINIEH,
    "Minieh—Danniyeh": TARGET_MINIEH,
    "ZahlÃ©": "Zahle", "Zahlé": "Zahle",
    "Bint Jbail": "Bint Jbeil",
    "Jbeil": "Byblos",
    "Saida": "Sidon",
    "Sour": "Tyre",
}
df["DistrictName"] = df["DistrictName"].replace(DISTRICT_ALIASES)

def first_present(frame: pd.DataFrame, *cands):
    for c in cands:
        if c in frame.columns:
            return c
    return None

# Required: springs
COL_SPRING_PERM = first_present(df, "Total number of permanent water springs", "Permanent springs", "Permanent")
COL_SPRING_SEAS = first_present(df, "Total number of seasonal water springs",   "Seasonal springs",   "Seasonal")
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
# Two-bucket tags (Governorates & Districts)
# ----------------------------
# Governorates: Urban (Mount Lebanon, North Lebanon, Beirut); Rural/Agri (others below)
GOV_BUCKET = {
    "Beirut": "Urban",
    "Mount Lebanon": "Urban",
    "North Lebanon": "Urban",
    "Bekaa": "Rural/Agri",
    "Baalbek-Hermel": "Rural/Agri",
    "Nabatieh": "Rural/Agri",
    "El Nabatieh": "Rural/Agri",
    "Akkar": "Rural/Agri",
    "South Lebanon": "Rural/Agri",
}

URBAN_DISTRICTS = {
    "Tripoli", "Sidon", "Tyre", "Baabda", "Metn", "Aley",
    "Keserwan", "Chouf","Zahle", "Byblos","Matn", "Jbeil",
}
RURAL_DISTRICTS = {
    "Baalbek", "Hermel", "West Bekaa", "Rachaya",
    "Bint Jbeil", "Marjeyoun", "Hasbaya", "Jezzine",
    TARGET_MINIEH,
    "Bcharre", "Koura", "Batroun", "Zgharta", "Akkar"
}

def area_bucket(row, level):
    g = str(row.get("GovernorateName", "")).strip()
    d = str(row.get("DistrictName", "")).strip()
    if level == "Governorate":
        return GOV_BUCKET.get(g, "Rural/Agri")
    if d in URBAN_DISTRICTS:
        return "Urban"
    if d in RURAL_DISTRICTS:
        return "Rural/Agri"
    return GOV_BUCKET.get(g, "Rural/Agri")

# ----------------------------
# Sidebar — aggregation & area filter
# ----------------------------
st.sidebar.header("Filters")

group_level = st.sidebar.radio("Aggregate by", ["Governorate", "District"], index=0)
GROUP_COL = "GovernorateName" if group_level == "Governorate" else "DistrictName"

area_choice = st.sidebar.radio(
    "Area profile (external)",
    ["All areas", "Urban only", "Agriculture/Rural only"],
    index=0
)

df["AreaBucket"] = df.apply(lambda r: area_bucket(r, group_level), axis=1)

data0 = df.copy()
if area_choice != "All areas":
    keep = "Urban" if area_choice == "Urban only" else "Rural/Agri"
    data0 = data0[data0["AreaBucket"] == keep]

areas_all = sorted([a for a in data0[GROUP_COL].dropna().unique().tolist() if a])
if len(areas_all) == 0:
    st.warning(
        f"No {group_level.lower()}s match **{area_choice}**. "
        "Try a different area profile or switch aggregation level."
    )
    st.stop()

pick_areas = st.sidebar.multiselect(f"{group_level}s", areas_all, default=areas_all)
if len(pick_areas) == 0:
    st.warning("No areas selected. Pick at least one.")
    st.stop()

# <-- THIS IS THE PIECE THAT WAS MISSING:
data = data0[data0[GROUP_COL].isin(pick_areas)].copy()
if data.empty:
    st.warning("No rows after filtering. Adjust your selections.")
    st.stop()

display_mode = st.sidebar.radio(
    "Springs scale",
    ["Totals", "Per-town average"],
    index=0,
    help="Per-town average divides by the number of unique towns per selected area."
)

# ----------------------------
# SAFE slider helper
# ----------------------------
def safe_topn_slider(label, n_items, key=None):
    n = int(n_items)
    if n <= 0:
        st.warning("Nothing to rank for the current filter.")
        st.stop()
    return st.sidebar.slider(label, min_value=1, max_value=n, value=min(8, n), key=key)

# ----------------------------
# Pyramid controls (reduced options)
# ----------------------------
st.sidebar.markdown("---")
st.sidebar.subheader("Pyramid sorting")
sort_opt = st.sidebar.selectbox(
    "Sort by",
    [
        "Total springs",
        "Seasonal only",
        "Permanent only",
    ],
    index=0,
)
ascending = st.sidebar.checkbox("Ascending order", value=False)
top_n_pyr = safe_topn_slider("Show top-N areas (after sort)", len(pick_areas), key="tn_pyr")

# ----------------------------
# Network controls
# ----------------------------
st.sidebar.markdown("---")
st.sidebar.subheader("Network sorting")
net_sort_opt = st.sidebar.selectbox("Sort by", ["Good %", "Bad %", "Acceptable %"], index=0)
net_ascending = st.sidebar.checkbox("Ascending", value=False, key="net_asc")
top_n_net = safe_topn_slider("Show top-N areas", len(pick_areas), key="tn_net")
show_labels_net = st.sidebar.checkbox("Show labels on bars", value=True)

# ----------------------------
# Viz 1: Pyramid — Permanent vs Seasonal
# ----------------------------
st.subheader(f"Permanent vs Seasonal Springs by {group_level}")

spr = data.groupby(GROUP_COL, as_index=False)[[COL_SPRING_PERM, COL_SPRING_SEAS]].sum()

if display_mode == "Per-town average" and HAS_TOWN:
    town_counts = data.groupby(GROUP_COL, as_index=False)["Town"].nunique().rename(columns={"Town":"Towns"})
    spr = spr.merge(town_counts, on=GROUP_COL, how="left")
    spr["Towns"] = spr["Towns"].replace(0, np.nan)
    spr[COL_SPRING_PERM] = (spr[COL_SPRING_PERM] / spr["Towns"]).round(2)
    spr[COL_SPRING_SEAS] = (spr[COL_SPRING_SEAS] / spr["Towns"]).round(2)
    x_title = "Avg springs per town"
else:
    x_title = "Number of springs"

spr["Total"] = spr[COL_SPRING_PERM] + spr[COL_SPRING_SEAS]

if sort_opt == "Total springs":
    spr = spr.sort_values("Total", ascending=ascending)
elif sort_opt == "Seasonal only":
    spr = spr.sort_values(COL_SPRING_SEAS, ascending=ascending)
elif sort_opt == "Permanent only":
    spr = spr.sort_values(COL_SPRING_PERM, ascending=ascending)

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
with st.expander("💡 Insights (Governorates vs District)"):
    st.markdown("""
**Governorates insights**
- **Akkar** shows the **strongest seasonal reliance** (~**539 seasonal** vs **269 permanent**) → highest risk of dry-season shortfalls (storage and summer operations are critical).
- **Mount Lebanon** is also **seasonal-heavy** (~**448** vs **257**) despite its size; plan for seasonal smoothing near urban demand.
- **Nabatieh** is extremely skewed (**~383 seasonal** vs **~17 permanent**) → very vulnerable in late summer.
- **Bekaa** is mid-range but still **seasonal > permanent** (~**150** vs **98**); good candidate for lifting the permanent base.
- **Baalbek-Hermel** is **balanced** (~**94** vs **93**), better year-round stability than its neighbors.
- **North Lebanon** contributes **very little** overall (~**16 seasonal**, **25 permanent**), totals are low regardless of type.

**District insights**
- **Baabda** is **seasonal-dominant** (≈ **318 seasonal** vs **150 permanent**), large urban demand leaning on wet-season recharge. Add **storage/transfer** to smooth summer gaps.
- **Aley** is **high on both** (≈ **263 permanent**, **226 seasonal**), big volumes overall (pair **source protection** with **pressure-managed** delivery).
- **Bsharri** and **Zahle** leans **permanent** (≈ **60 perm / 41 seas** and **49 perm / 31 seas**) — valuable **dry-season buffer** from high-elevation baseflow.
- **Miniyeh-Danniyeh**, **Marjeyoun** and **Hasbaya** sits mid-pack (≈ **63 perm / 58 seas**, **39 perm / 31 seas** and **33 perm / 35 seas**), somewhat balanced springs.

**What to act on:** 
Prioritize storage/transfer in **Akkar** and **Nabatieh**, strengthen permanent sources in **Mount Lebanon** and **Bekaa**, and keep **Baalbek-Hermel** reliable with protection of existing permanent flows.

""")
    
with st.expander("🏙️ Urban vs 🌾 Agriculture/Rural"):
    st.markdown("""
**Urban (Mount Lebanon, North Lebanon)**
- **Mount Lebanon** has **big seasonal bars** (seasonal >> permanent) → even the urban core rides on **wet-season recharge**. That means **storage/transfer** are essential for summer.
- **North Lebanon** has **small totals** overall → fewer mapped springs; plan for **diversification** (interconnections/groundwater where safe), not just relying on local springs.

**Agriculture/Rural (Akkar, Bekaa, Baalbek-Hermel, Nabatieh, South)**
- **Akkar & Nabatieh** are **seasonal-heavy hotspots** → highest exposure to **dry-season shortfalls**; prioritize **tanks/reservoirs** and **summer operations**.
- **Bekaa** is mid-range but still **seasonal > permanent** → lift the **permanent base** (spring protection, wellfield rehab).
- **Baalbek-Hermel** is **balanced** (seasonal ≈ permanent) → more stable year-round on sources, but see network condition chart for delivery issues.
- **South** tends to be **moderate** on volumes with seasonal lean; plan **targeted storage** near demand centers.

**Bottom line:** Urban demand does **not** guarantee permanent stability; several **urban/peri-urban districts** are still **seasonal-dependent**. Rural belts carry the **largest seasonal swings**, so **storage + operational smoothing** matter most there as it will ultimately affect the agricultral seasons and affect crop harvest.
""")


# ----------------------------
# Viz 2: Network condition — 100% stacked bar
# ----------------------------
st.subheader(f"State of Water Network by {group_level} (100% Stacked)")

if COL_STATE_GOOD and COL_STATE_ACC and COL_STATE_BAD:
    net = data.groupby(GROUP_COL, as_index=False)[[COL_STATE_GOOD, COL_STATE_ACC, COL_STATE_BAD]].sum()

    vals = net[[COL_STATE_GOOD, COL_STATE_ACC, COL_STATE_BAD]].astype(float)
    row_sum = vals.sum(axis=1).replace(0, np.nan)
    net_pct = (vals.div(row_sum, axis=0) * 100).round(1)
    net_pct[GROUP_COL] = net[GROUP_COL]

    sort_key_map = {"Good %": COL_STATE_GOOD, "Bad %": COL_STATE_BAD, "Acceptable %": COL_STATE_ACC}
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
        color_discrete_map={"Good %": "#2ECC71", "Acceptable %": "#F1C40F", "Bad %": "#E74C3C"},
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
else:
    st.info("Network condition columns not found — this chart is disabled for this CSV.")

with st.expander("💡 Insights (Governorates vs District — Network condition)"):
    st.markdown("""
**Governorates insights: Network condition**
- **Baalbek-Hermel** is the **weakest**: **very low Good%** and **high Bad%** → first in the rehab queue since towns are dispersed, pipes are old/lengthy, and pumps experience power outages (which results in low pressure/more leaks/poorer water).
- **Mount Lebanon** is **Acceptable-heavy** with a notable **Bad%** → classic urban stress; convert **Yellow→Green** via pressure management and leak reduction (DMAs/PRVs).
- **Bekaa** is **mixed**, it has decent **Good%** but a **meaningful Bad%** pointing to uneven performance across towns.
- **North Lebanon** tends to look **healthier** (higher **Good%**, lower **Bad%**) than **Mount Lebanon**.
- **South Lebanon** generally holds a **balanced** profile with **lower Bad%** than the eastern belt.

**District insights: Network condition**
  - **Zgharta** is the **best performer** (higher **Good%**, lower **Bad%**) → protect with **preventive O&M**.
  - **Byblos (Jbeil)** is the **urban outlier** with one of the **high Bad%**; **Marjeyoun** and **Sidon** also show **elevated Bad%** → prioritize **leak detection** and targeted renewals.
  - **Aley / Keserwan** are **Acceptable-heavy** → quick wins by converting **Yellow→Green** via **loss reduction** and **pressure management**.
  - **Baabda** and **Western Bekaa** are **bright spots** (low **Bad%**, great **Good%**) → keep them green with **condition-based maintenance**.
  - **Bint Jbeil**, **Zahle**, **Hermel** show **high Bad%**; **Hasbaya** is also elevated → these are the **first rehab queue** (mains renewal, valve rehab, metering, step-testing).
  - **Matn** tends to be **Acceptable-heavy** → not failing, but room to lift service quality with **pressure/NRW** programs.
- **Cross-signal:** Districts that are **seasonal-heavy** in the springs chart often show **more Yellow/Red** here → consistent with **dry-season strain** and **pressure swings**. Pair **network fixes** with **summer operations** and **storage**.

**What to act on:** 
Rehab **Baalbek-Hermel** first; target hotspots in **Bekaa**; optimize **Mount Lebanon** operations; keep **North/South** green with preventive maintenance.
""")


with st.expander("🏙️ Urban vs 🌾 Agriculture/Rural"):
    st.markdown("""
**Urban (Mount Lebanon, North Lebanon)**
- **North Lebanon** tends to look **healthier** (higher **Good%**, lower **Bad%**).
- **Mount Lebanon** is **Acceptable-heavy** with non-trivial **Bad%**, this is classic urban stress (aging assets, pressure/leak issues). **leak detection, and valve rehab** can move **Yellow → Green** fast.

**Agriculture/Rural (Akkar, Bekaa, Baalbek-Hermel, Nabatieh, South)**
- **Baalbek-Hermel** is the **rehab front-runner**: very low **Good%**, high **Bad%** → **first in the capex queue** (mains renewal, pressure zoning, metering).
- **Bekaa** is **uneven** (decent Good% yet meaningful Bad%) → target **pockets** rather than one-size-fits-all.
- **Akkar & Nabatieh** often show **elevated Bad%** in places—pair **network fixes** with the seasonal dependence seen in the springs chart.
- **South** generally more **balanced** → protect with **preventive maintenance** so it doesn’t slide.

**Bottom line:** Rural belts need **hard upgrades** where **Bad%** clusters (especially **Baalbek-Hermel**), while **urban Mount Lebanon** benefits most from **operational optimization** (pressure/leaks) before major capex. Use this split to justify **different playbooks** by area type.
""")













