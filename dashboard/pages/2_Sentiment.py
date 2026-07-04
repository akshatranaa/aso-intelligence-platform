"""Sentiment page — review sentiment breakdown and themes."""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import streamlit as st
import plotly.express as px
import pandas as pd
from utils import api_get, require_app_id

st.set_page_config(page_title="Sentiment", page_icon="💬", layout="wide")
st.title("💬 Sentiment Analysis")

app_id = require_app_id()
if not app_id:
    st.stop()

sentiment = api_get(f"/app/{app_id}/sentiment")
if not sentiment:
    st.stop()

# ── Summary metrics ───────────────────────────────────────────────────────────
c1, c2, c3, c4 = st.columns(4)
c1.metric("Total Reviews",  sentiment.get("total_reviews", 0))
c2.metric("Positive",       f"{sentiment.get('positive_pct', 0)}%")
c3.metric("Negative",       f"{sentiment.get('negative_pct', 0)}%")
c4.metric("Reviews Avg",    f"{sentiment.get('avg_rating', 0)} ⭐",
          help="Average rating of the recent reviews collected here — a small, "
               "recency-skewed sample, NOT the app's official all-time store rating.")

st.divider()

# ── Pie chart ─────────────────────────────────────────────────────────────────
left, right = st.columns([1, 1])

with left:
    st.subheader("Sentiment Breakdown")
    pie_data = {
        "Label":   ["Positive", "Negative", "Neutral"],
        "Count":   [
            sentiment.get("positive_count", 0),
            sentiment.get("negative_count", 0),
            sentiment.get("neutral_count",  0),
        ],
    }
    fig = px.pie(
        pie_data,
        names="Label",
        values="Count",
        color="Label",
        color_discrete_map={
            "Positive": "#00C851",
            "Negative": "#FF4444",
            "Neutral":  "#FF8800",
        },
        hole=0.4,
    )
    fig.update_layout(margin=dict(t=0, b=0, l=0, r=0))
    st.plotly_chart(fig, use_container_width=True)

with right:
    st.subheader("Rating Distribution")
    reviews_data = api_get(f"/app/{app_id}/reviews")
    if reviews_data and reviews_data.get("reviews"):
        reviews = reviews_data["reviews"]
        rating_counts = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
        for r in reviews:
            rating = r.get("rating")
            if rating in rating_counts:
                rating_counts[rating] += 1
        df_ratings = pd.DataFrame({
            "Rating": [f"{'⭐' * i} ({i})" for i in range(5, 0, -1)],
            "Count":  [rating_counts[i] for i in range(5, 0, -1)],
        })
        fig2 = px.bar(
            df_ratings,
            x="Count",
            y="Rating",
            orientation="h",
            color="Count",
            color_continuous_scale=["#FF4444", "#FF8800", "#00C851"],
        )
        fig2.update_layout(margin=dict(t=0, b=0, l=0, r=0), showlegend=False)
        st.plotly_chart(fig2, use_container_width=True)

st.divider()

# ── Recent reviews table ──────────────────────────────────────────────────────
st.subheader("Recent Reviews")
reviews_data = reviews_data or api_get(f"/app/{app_id}/reviews")
if reviews_data and reviews_data.get("reviews"):
    reviews = reviews_data["reviews"]
    df = pd.DataFrame(reviews)[["rating", "sentiment_label", "review_text", "author", "review_date"]]
    df.columns = ["Rating", "Sentiment", "Review", "Author", "Date"]
    df = df.fillna("N/A")

    label_filter = st.selectbox("Filter by sentiment", ["All", "positive", "negative", "neutral"])
    if label_filter != "All":
        df = df[df["Sentiment"] == label_filter]

    st.dataframe(df.head(50), use_container_width=True, hide_index=True)
