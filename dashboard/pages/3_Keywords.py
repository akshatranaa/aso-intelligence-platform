"""Keywords page — keyword scores, opportunities, and gap analysis."""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import streamlit as st
import plotly.express as px
import pandas as pd
from utils import api_get, require_app_id, seed_warning_banner

st.set_page_config(page_title="Keywords", page_icon="🔑", layout="wide")
st.title("🔑 Keyword Analysis")

app_id = require_app_id()
if not app_id:
    st.stop()

seed_warning_banner(app_id)

data = api_get(f"/app/{app_id}/keywords?k=50")
if not data:
    st.stop()

own  = data.get("top_keywords", [])
gaps = data.get("gap_keywords", [])

# ── Summary metrics ───────────────────────────────────────────────────────────
c1, c2, c3 = st.columns(3)
c1.metric("Total Keywords", len(own) + len(gaps))
c2.metric("Opportunity Keywords", len(own))
c3.metric("Gap Keywords",         len(gaps))

st.divider()

# ── Tab layout ────────────────────────────────────────────────────────────────
tab1, tab2 = st.tabs(["📊 Opportunity Keywords", "🎯 Gap Keywords"])

with tab1:
    if own:
        df_own = pd.DataFrame(own)
        score_col = "proxy_opportunity"

        # Bar chart — top 20 by opportunity score
        top20 = sorted(own, key=lambda k: k.get(score_col, 0), reverse=True)[:20]
        fig = px.bar(
            pd.DataFrame(top20),
            x=score_col,
            y="keyword",
            orientation="h",
            color=score_col,
            color_continuous_scale="Blues",
            title="Top 20 Keywords by Opportunity Score",
        )
        fig.update_layout(yaxis={"categoryorder": "total ascending"}, margin=dict(t=40))
        st.plotly_chart(fig, use_container_width=True)

        # Full table
        display_cols = ["keyword", "proxy_opportunity", "proxy_volume",
                        "proxy_difficulty", "source"]
        df_display = df_own[[c for c in display_cols if c in df_own.columns]]
        df_display = df_display.sort_values("proxy_opportunity", ascending=False)
        df_display.columns = [c.replace("proxy_", "").replace("_", " ").title()
                               for c in df_display.columns]
        st.dataframe(df_display, use_container_width=True, hide_index=True)
    else:
        st.info("No opportunity keywords yet. Run collection first.")

with tab2:
    if gaps:
        df_gaps = pd.DataFrame(gaps)

        fig2 = px.bar(
            df_gaps.sort_values("proxy_opportunity", ascending=True),
            x="proxy_opportunity",
            y="keyword",
            orientation="h",
            color="gap_competitor",
            title="Gap Keywords by Opportunity Score (coloured by competitor)",
        )
        fig2.update_layout(yaxis={"categoryorder": "total ascending"}, margin=dict(t=40))
        st.plotly_chart(fig2, use_container_width=True)

        display_cols = ["keyword", "proxy_opportunity", "gap_competitor", "proxy_volume"]
        df_display2 = df_gaps[[c for c in display_cols if c in df_gaps.columns]]
        df_display2 = df_display2.sort_values("proxy_opportunity", ascending=False)
        df_display2.columns = [c.replace("proxy_", "").replace("_", " ").title()
                                for c in df_display2.columns]
        st.dataframe(df_display2, use_container_width=True, hide_index=True)
    else:
        st.info("No gap keywords found. Ensure competitors are collected first.")
