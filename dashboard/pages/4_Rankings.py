"""Rankings page — keyword rank tracking and velocity."""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import streamlit as st
import plotly.express as px
import pandas as pd
from utils import api_get, trend_badge, require_app_id

st.set_page_config(page_title="Rankings", page_icon="📈", layout="wide")
st.title("📈 Keyword Rankings")

app_id = require_app_id()
if not app_id:
    st.stop()

data = api_get(f"/app/{app_id}/rankings")
if not data:
    st.stop()

rankings = data.get("rankings", [])

if not rankings:
    st.info("No rankings data yet. Run collection first.")
    st.stop()

# ── Summary metrics ───────────────────────────────────────────────────────────
ranked    = [r for r in rankings if r.get("rank") is not None]
improving = [r for r in rankings if r.get("trend") == "improving"]
declining = [r for r in rankings if r.get("trend") == "declining"]

c1, c2, c3, c4 = st.columns(4)
c1.metric("Keywords Tracked", len(rankings))
c2.metric("Currently Ranked", len(ranked))
c3.metric("Improving",        len(improving))
c4.metric("Declining",        len(declining))

st.divider()

# ── Rankings table ────────────────────────────────────────────────────────────
st.subheader("Keyword Rankings Overview")

df = pd.DataFrame(rankings)

# Apply trend badge
if "trend" in df.columns:
    df["Trend"] = df["trend"].apply(trend_badge)

if "delta" in df.columns:
    df["Delta"] = df["delta"].apply(lambda d: f"{d:+d}" if d is not None else "N/A")

if "velocity" in df.columns:
    df["Velocity"] = df["velocity"].apply(
        lambda v: f"{v:+.2f}" if v is not None else "N/A"
    )

# Sort: ranked first (ascending), then unranked
ranked_df   = df[df["rank"].notna()].sort_values("rank")
unranked_df = df[df["rank"].isna()]
df_sorted   = pd.concat([ranked_df, unranked_df])

display_cols = {
    "keyword":  "Keyword",
    "rank":     "Rank",
    "Delta":    "Delta",
    "Velocity": "Velocity (avg/day)",
    "Trend":    "Trend",
}
available = {k: v for k, v in display_cols.items() if k in df_sorted.columns}
df_display = df_sorted[list(available.keys())].rename(columns=available)
df_display["Rank"] = df_display["Rank"].apply(
    lambda r: f"#{int(r)}" if pd.notna(r) else "Unranked"
)

st.dataframe(df_display, use_container_width=True, hide_index=True)

st.divider()

# ── Scatter plot: rank vs velocity ────────────────────────────────────────────
scatter_df = df[df["rank"].notna() & df["velocity"].notna()].copy()
if not scatter_df.empty:
    st.subheader("Rank vs Velocity")
    st.caption("Negative velocity = rank number decreasing = climbing (good)")
    fig = px.scatter(
        scatter_df,
        x="rank",
        y="velocity",
        text="keyword",
        color="trend",
        color_discrete_map={
            "improving": "#00C851",
            "declining": "#FF4444",
            "stable":    "#FF8800",
            "unknown":   "#AAAAAA",
        },
        labels={"rank": "Current Rank", "velocity": "Avg Daily Rank Change"},
    )
    fig.add_hline(y=0, line_dash="dash", line_color="grey")
    fig.update_traces(textposition="top center")
    fig.update_layout(margin=dict(t=20))
    st.plotly_chart(fig, use_container_width=True)
