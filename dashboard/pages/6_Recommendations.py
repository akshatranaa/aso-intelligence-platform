"""Recommendations page — priority actions and description suggestions."""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import streamlit as st
from utils import (
    active_country_selector,
    api_get,
    loading_overlay,
    priority_badge,
    require_app_id,
)

st.set_page_config(page_title="Recommendations", page_icon="⭐", layout="wide")
st.title("⭐ Recommendations")

app_id = require_app_id()
if not app_id:
    st.stop()

country = active_country_selector(app_id)
_p = {"country": country} if country else {}

# ── LLM toggle ────────────────────────────────────────────────────────────────
use_llm = st.toggle(
    "Use LLM for deeper analysis (costs API credits)",
    value=False,
    help="Enabling this sends data to the AI model for richer insights.",
)

with loading_overlay("Generating recommendations…"):
    data = api_get(
        f"/app/{app_id}/recommendations",
        params={"use_llm": str(use_llm).lower(), **_p},
    )

if not data:
    st.stop()

# ── Priority actions ───────────────────────────────────────────────────────────
st.subheader("🎯 Priority Actions")
actions = data.get("priority_actions", [])
if actions:
    for action in actions:
        badge = priority_badge(action.get("priority", ""))
        area  = action.get("area", "").upper()
        text  = action.get("action", "")
        with st.container(border=True):
            st.markdown(f"**{badge}** &nbsp; `{area}`")
            st.write(text)
else:
    st.info("No priority actions generated.")

st.divider()

# ── Keyword recommendations ────────────────────────────────────────────────────
st.subheader("🔑 Keyword Recommendations")
kw_rec = data.get("keyword_recommendations", {})
if kw_rec:
    cols = st.columns(4)
    buckets = [
        ("prioritise",   "🟢 Prioritise",  "High opportunity, unranked — go after these."),
        ("defend",       "🔵 Defend",       "Already ranking top 10 — protect these."),
        ("target_gaps",  "🟡 Target Gaps",  "Competitors rank for these, you don't."),
        ("drop",         "⚫ Drop",          "Low opportunity — deprioritise."),
    ]
    for col, (key, label, caption) in zip(cols, buckets):
        kws = kw_rec.get(key, [])
        with col:
            st.markdown(f"**{label}**")
            st.caption(caption)
            if kws:
                for kw in kws[:10]:
                    name  = kw.get("keyword", "")
                    score = kw.get("proxy_opportunity") or kw.get("revised_opportunity") or 0
                    st.markdown(f"- `{name}` ({score:.2f})")
            else:
                st.write("—")
else:
    st.info("No keyword recommendations available.")

st.divider()

# ── Sentiment themes ───────────────────────────────────────────────────────────
st.subheader("💬 Sentiment Insights")
sentiment_rec = data.get("sentiment_recommendations", {})
if sentiment_rec:
    left, right = st.columns(2)
    with left:
        complaints = sentiment_rec.get("top_complaints") or []
        st.markdown("**Top Complaints**")
        if complaints:
            for c in complaints:
                st.markdown(f"- {c}")
        else:
            st.write("—")
    with right:
        praise = sentiment_rec.get("top_praise") or []
        st.markdown("**Top Praise**")
        if praise:
            for p in praise:
                st.markdown(f"- {p}")
        else:
            st.write("—")

    summary = sentiment_rec.get("sentiment_summary")
    if summary:
        st.info(summary)

    fix = sentiment_rec.get("priority_fix")
    if fix:
        st.warning(f"**Priority Fix:** {fix}")
else:
    st.info("No sentiment recommendations available.")

st.divider()

# ── Competitor insights ────────────────────────────────────────────────────────
st.subheader("🏆 Competitor Insights")
comp_rec = data.get("competitor_recommendations", {})
if comp_rec:
    left, right = st.columns(2)
    with left:
        st.markdown("**Competitor Advantages**")
        for item in (comp_rec.get("competitor_advantages") or []):
            st.markdown(f"- {item}")
    with right:
        st.markdown("**Your Advantages**")
        for item in (comp_rec.get("target_advantages") or []):
            st.markdown(f"- {item}")

    missing = comp_rec.get("missing_keywords") or []
    if missing:
        st.markdown("**Missing Keywords** (in competitor description but not yours)")
        st.write(", ".join(f"`{kw}`" for kw in missing))

    rec_text = comp_rec.get("recommendation")
    if rec_text:
        st.info(rec_text)
else:
    st.info("No competitor recommendations available (requires LLM or tier1 competitor).")

st.divider()

# ── Description rewrite ────────────────────────────────────────────────────────
st.subheader("✍️ Suggested Description Rewrite")
new_desc = data.get("suggested_description")
if new_desc:
    st.markdown(new_desc)
    st.caption(f"Character count: {len(new_desc)} / 4000")
else:
    st.info("Enable LLM toggle above to generate a description rewrite suggestion.")

# ── Keyword narrative ──────────────────────────────────────────────────────────
narrative = data.get("keyword_narrative")
if narrative:
    st.divider()
    st.subheader("📖 Keyword Strategy")
    st.write(narrative)
