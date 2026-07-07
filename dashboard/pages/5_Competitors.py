"""Competitors page — competitor discovery and scoring."""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import streamlit as st
import plotly.express as px
import pandas as pd
from utils import (
    active_country_selector,
    api_get,
    loading_overlay,
    require_app_id,
    seed_warning_banner,
)

st.set_page_config(page_title="Competitors", page_icon="🏆", layout="wide")
st.title("🏆 Competitor Analysis")

app_id = require_app_id()
if not app_id:
    st.stop()

seed_warning_banner(app_id)

country = active_country_selector(app_id)
_p = {"country": country} if country else None

with st.expander("ℹ️ How competitors are assessed"):
    st.markdown(
        """
**1. Discovery** — we search the App Store for up to **5 seed keywords** (derived
from your app's name, category, and — with *Use LLM* on — an AI-generated list of
what real users would search) and collect the **top 15 apps** for each, forming a
candidate pool of ~75 apps.

**2. Relevance gate (the important part)** — an **AI judge** reads your app and each
candidate (name, category, description) and keeps only **genuine direct competitors**
— apps with the same core purpose. This is why merely-popular but unrelated apps
(ChatGPT, Calculator, Chrome) are excluded even when they show up in search.
*(With Use LLM off, a plain same-category filter is used instead.)*

**3. Popularity score** — the kept competitors are ranked by a popularity score so the
strongest appear first:

`score = 0.70 × min(rating_count ÷ 1,000,000, 1.0)  +  0.30 × (avg_rating − 1) ÷ 4`

**4. Tiers** —
- **Tier 1**: shares your app's category **and** scores ≥ **0.40** (your closest, strongest rivals).
- **Tier 2**: every other genuine competitor the judge kept.
        """
    )

with loading_overlay("Loading competitors…"):
    data = api_get(f"/app/{app_id}/competitors", params=_p)
if not data:
    st.stop()

tier1 = data.get("tier1", [])
tier2 = data.get("tier2", [])
all_competitors = tier1 + tier2

if not all_competitors:
    st.info("No competitors found. Run collection first.")
    st.stop()

# ── Summary metrics ───────────────────────────────────────────────────────────
c1, c2, c3 = st.columns(3)
c1.metric("Total Competitors", len(all_competitors))
c2.metric("Tier 1 (top, same-category)", len(tier1))
c3.metric("Tier 2 (other relevant)", len(tier2))

st.divider()

# ── Competitor score bar chart ────────────────────────────────────────────────
st.subheader("Competitor Scores")
df_all = pd.DataFrame(all_competitors)
if "competitor_score" in df_all.columns and "name" in df_all.columns:
    df_chart = df_all.sort_values("competitor_score", ascending=True)
    fig = px.bar(
        df_chart,
        x="competitor_score",
        y="name",
        orientation="h",
        color="competitor_tier",
        color_discrete_map={"tier1": "#FF4444", "tier2": "#FF8800"},
        labels={"competitor_score": "Competitor Score", "name": "App", "competitor_tier": "Tier"},
    )
    fig.update_layout(yaxis={"categoryorder": "total ascending"}, margin=dict(t=10))
    st.plotly_chart(fig, use_container_width=True)

st.divider()

# ── Tier tabs ─────────────────────────────────────────────────────────────────
tab1, tab2 = st.tabs([f"🔴 Tier 1 ({len(tier1)})", f"🟠 Tier 2 ({len(tier2)})"])

def _render_competitor_table(apps: list[dict]) -> None:
    if not apps:
        st.info("No competitors in this tier.")
        return
    display_cols = ["name", "competitor_score", "avg_rating",
                    "rating_count", "category", "seller_name"]
    df = pd.DataFrame(apps)
    df_display = df[[c for c in display_cols if c in df.columns]]
    df_display = df_display.sort_values("competitor_score", ascending=False)
    df_display.columns = [c.replace("_", " ").title() for c in df_display.columns]
    if "Rating Count" in df_display.columns:
        df_display["Rating Count"] = df_display["Rating Count"].apply(
            lambda x: f"{int(x):,}" if pd.notna(x) else "N/A"
        )
    if "Competitor Score" in df_display.columns:
        df_display["Competitor Score"] = df_display["Competitor Score"].apply(
            lambda x: f"{x:.4f}" if pd.notna(x) else "N/A"
        )
    st.dataframe(df_display, use_container_width=True, hide_index=True)

with tab1:
    _render_competitor_table(tier1)

with tab2:
    _render_competitor_table(tier2)

# ── Rating comparison scatter ─────────────────────────────────────────────────
st.divider()
st.subheader("Rating vs Rating Count")
target_app = api_get(f"/app/{app_id}", params=_p)
if target_app and "avg_rating" in df_all.columns:
    scatter_df = df_all[df_all["avg_rating"].notna() & df_all["rating_count"].notna()].copy()
    if not scatter_df.empty:
        target_row = pd.DataFrame([{
            "name":             target_app["name"],
            "avg_rating":       target_app.get("avg_rating", 0),
            "rating_count":     target_app.get("rating_count", 0),
            "competitor_tier":  "target",
        }])
        plot_df = pd.concat([scatter_df[["name", "avg_rating", "rating_count", "competitor_tier"]],
                             target_row], ignore_index=True)
        fig2 = px.scatter(
            plot_df,
            x="rating_count",
            y="avg_rating",
            text="name",
            color="competitor_tier",
            color_discrete_map={"tier1": "#FF4444", "tier2": "#FF8800", "target": "#0088FF"},
            labels={"rating_count": "Rating Count", "avg_rating": "Avg Rating"},
        )
        fig2.update_traces(textposition="top center")
        fig2.update_layout(margin=dict(t=10))
        st.plotly_chart(fig2, use_container_width=True)
