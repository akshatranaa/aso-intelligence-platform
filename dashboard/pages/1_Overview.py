"""Overview page — key metrics and priority actions at a glance."""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import streamlit as st
from utils import api_get, priority_badge, require_app_id

st.set_page_config(page_title="Overview", page_icon="🏠", layout="wide")
st.title("🏠 Overview")

app_id = require_app_id()
if not app_id:
    st.stop()

# ── App metadata ──────────────────────────────────────────────────────────────
app_data = api_get(f"/app/{app_id}")
if not app_data:
    st.stop()

st.subheader(f"{app_data['name']}")
st.caption(f"{app_data.get('category', '')}  ·  {app_data.get('seller_name', '')}")
st.divider()

# ── Key metrics row ───────────────────────────────────────────────────────────
c1, c2, c3, c4 = st.columns(4)
c1.metric("Avg Rating",   f"{app_data.get('avg_rating', 'N/A')} ⭐")
c2.metric("Total Ratings", f"{app_data.get('rating_count', 0):,}")
c3.metric("Price",         f"${app_data.get('price', 0):.2f}")
c4.metric("Min iOS",       app_data.get("min_os_version", "N/A"))

st.divider()

# ── Sentiment snapshot ────────────────────────────────────────────────────────
sentiment = api_get(f"/app/{app_id}/sentiment")
if sentiment:
    st.subheader("💬 Sentiment Snapshot")
    s1, s2, s3, s4 = st.columns(4)
    s1.metric("Total Reviews",   sentiment.get("total_reviews", 0))
    s2.metric("Positive",        f"{sentiment.get('positive_pct', 0)}%")
    s3.metric("Negative",        f"{sentiment.get('negative_pct', 0)}%")
    s4.metric("Reviews Avg",     f"{sentiment.get('avg_rating', 0)} ⭐",
              help="Average rating of the recent reviews collected — a recency-skewed "
                   "sample, NOT the app's official all-time store rating (shown above).")
    st.divider()

# ── Ranking snapshot ──────────────────────────────────────────────────────────
rankings = api_get(f"/app/{app_id}/rankings")
if rankings and rankings.get("rankings"):
    st.subheader("📈 Rankings Snapshot")
    rows = rankings["rankings"][:5]
    cols = st.columns(len(rows))
    for col, row in zip(cols, rows):
        delta = row.get("delta")
        delta_str = f"{delta:+d}" if delta is not None else "N/A"
        col.metric(
            label=row["keyword"],
            value=f"#{row['rank']}" if row.get("rank") else "Unranked",
            delta=delta_str,
        )
    st.divider()

# ── Priority actions ──────────────────────────────────────────────────────────
st.subheader("⭐ Priority Actions")
recommendations = api_get(f"/app/{app_id}/recommendations?use_llm=false")
if recommendations and recommendations.get("priority_actions"):
    for action in recommendations["priority_actions"]:
        badge = priority_badge(action.get("priority", ""))
        area  = action.get("area", "").upper()
        text  = action.get("action", "")
        st.markdown(f"**{badge}** &nbsp; `{area}` &nbsp; {text}")
else:
    st.info("No priority actions yet. Run collection first.")
