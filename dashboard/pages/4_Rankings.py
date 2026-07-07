"""Rankings page — keyword rank tracking and velocity."""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import streamlit as st
import plotly.express as px
import pandas as pd
from utils import (
    api_get,
    api_post,
    country_label,
    country_selectbox,
    loading_overlay,
    trend_badge,
    require_app_id,
)

st.set_page_config(page_title="Rankings", page_icon="📈", layout="wide")
st.title("📈 Keyword Rankings")

app_id = require_app_id()
if not app_id:
    st.stop()

with loading_overlay("Loading rankings…"):
    data = api_get(f"/app/{app_id}/rankings")
if data is None:
    st.stop()

rankings = data.get("rankings", [])

# ── Actions: track a keyword / refresh all ────────────────────────────────────
ac1, ac2 = st.columns([3, 1])
with ac1:
    new_kw = st.text_input(
        "Track a new keyword",
        placeholder="e.g. secure vpn",
        key="track_kw",
        label_visibility="collapsed",
    )
with ac2:
    if st.button("➕ Track keyword", use_container_width=True):
        kw = new_kw.strip()
        if not kw:
            st.warning("Enter a keyword to track.")
        else:
            with loading_overlay(f"Fetching rank for '{kw}'…"):
                res = api_post(f"/app/{app_id}/rankings/track", params={"keyword": kw})
            if res:
                st.success(f"Now tracking '{kw}'.")
                st.rerun()

if st.button(
    "🔄 Re-run ranking analysis",
    help="Re-check ranks for every tracked keyword — no full collection needed.",
):
    with loading_overlay("Refreshing all tracked keyword ranks…"):
        res = api_post(f"/app/{app_id}/rankings/refresh")
    if res:
        st.success("Rankings refreshed.")
        st.rerun()

st.divider()

if not rankings:
    st.info("No rankings yet. Track a keyword above, or run a collection from Home.")
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
    df["Delta"] = df["delta"].apply(
        lambda d: f"{int(d):+d}" if pd.notna(d) else "N/A"
    )

if "velocity" in df.columns:
    df["Velocity"] = df["velocity"].apply(
        lambda v: f"{v:+.2f}" if pd.notna(v) else "N/A"
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

st.divider()

# ── Competitor rank comparison ────────────────────────────────────────────────
st.subheader("🆚 Competitor Rank Comparison")
st.caption(
    "See where your top competitors rank for a keyword — in any country, "
    "independent of where the app was collected (lower rank = better)."
)

# Default the country to whatever the app was collected for (but let it change).
app_meta = api_get(f"/app/{app_id}") or {}
default_country = (app_meta.get("country") or "in").lower()

kw_options = [r["keyword"] for r in rankings]
comp_col1, comp_col2 = st.columns([2, 1])
with comp_col1:
    sel_kw = st.selectbox("Keyword to compare", kw_options)
with comp_col2:
    compare_country = country_selectbox(
        "Country", key="compare_country", default=default_country
    )

n_competitors = st.slider(
    "How many competitors to compare (top N by popularity)",
    min_value=1,
    max_value=25,
    value=5,
    help="Each competitor adds ~1s of live lookup time (25 ≈ half a minute).",
)
do_compare = st.button("Compare competitors", use_container_width=True)

if do_compare and sel_kw:
    with loading_overlay(
        f"Looking up ranks for '{sel_kw}' across {n_competitors} competitors "
        f"in {country_label(compare_country)}… (~{n_competitors + 1}s)"
    ):
        cmp = api_get(
            f"/app/{app_id}/rankings/compare",
            params={
                "keyword": sel_kw,
                "n": n_competitors,
                "country": compare_country,
            },
        )
    if cmp:
        rows = [{"App": f"{cmp['target']['name']} (you)", "Rank": cmp["target"]["rank"]}]
        rows += [{"App": c["name"], "Rank": c["rank"]} for c in cmp["competitors"]]
        cdf = pd.DataFrame(rows)
        cdf["Rank label"] = cdf["Rank"].apply(
            lambda r: f"#{int(r)}" if pd.notna(r) else "Unranked"
        )

        ranked_cmp = cdf[cdf["Rank"].notna()]
        if not ranked_cmp.empty:
            fig_c = px.bar(
                ranked_cmp.sort_values("Rank"),
                x="Rank",
                y="App",
                orientation="h",
                text="Rank label",
                title=f"Rank for '{sel_kw}' (shorter bar = better rank)",
            )
            fig_c.update_layout(
                yaxis={"categoryorder": "total descending"},
                showlegend=False,
                margin=dict(t=40),
            )
            st.plotly_chart(fig_c, use_container_width=True)

        st.dataframe(
            cdf[["App", "Rank label"]].rename(columns={"Rank label": "Rank"}),
            use_container_width=True,
            hide_index=True,
        )
        if not cmp["competitors"]:
            st.info("No competitors stored for this app yet — run a collection first.")
