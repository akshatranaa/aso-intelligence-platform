"""ASO Intelligence Platform — Home page and app selector."""

import time

import streamlit as st
from utils import (
    api_get,
    api_post,
    country_label,
    country_selectbox,
    render_loading_overlay,
)

_POLL_INTERVAL_SECONDS = 5

st.set_page_config(
    page_title="ASO Intelligence Platform",
    page_icon="📱",
    layout="wide",
)

st.title("📱 ASO Intelligence Platform")
st.caption("App Store Optimization powered by AI")
st.divider()

# Initialise session state
if "app_id" not in st.session_state:
    st.session_state.app_id = None
if "app_name" not in st.session_state:
    st.session_state.app_name = None

# ── Two columns: collect new app | load existing app ──────────────────────────
left, right = st.columns(2)

with left:
    st.subheader("🔍 Collect New App")
    st.caption("Search the App Store and run the full analysis pipeline.")
    app_name_input = st.text_input("App name", placeholder="e.g. Spotify")
    collect_country = country_selectbox("App Store country", key="collect_country")
    use_llm = st.checkbox("Use LLM during analysis (costs API credits)", value=False)

    if st.button("Collect ▶", type="primary", use_container_width=True):
        if not app_name_input.strip():
            st.warning("Please enter an app name.")
        else:
            start = api_post(
                f"/collect/{app_name_input.strip()}",
                params={"use_llm": use_llm, "country": collect_country},
            )

            if start and start.get("job_id"):
                job_id = start["job_id"]
                overlay = st.empty()
                result = None
                elapsed = 0
                country_name = country_label(collect_country)

                while True:
                    render_loading_overlay(
                        overlay,
                        f"Collecting '{app_name_input.strip()}' for {country_name}…"
                        f"<br>Running the full pipeline — this takes a few minutes."
                        f"<br>({elapsed}s elapsed)",
                    )
                    job = api_get(f"/collect/status/{job_id}")
                    if not job:
                        st.error("Lost connection while checking job status.")
                        break
                    if job["status"] == "done":
                        result = job["result"]
                        break
                    if job["status"] == "error":
                        st.error(f"Collection failed: {job.get('detail', 'unknown error')}")
                        break
                    time.sleep(_POLL_INTERVAL_SECONDS)
                    elapsed += _POLL_INTERVAL_SECONDS

                overlay.empty()
                if result:
                    st.session_state.app_id   = result["app_id"]
                    st.session_state.app_name = result["app_name"]
                    # Analysis pages open on the country just collected.
                    st.session_state.active_country = result.get(
                        "country", collect_country
                    )
                    # Remember any seed-fallback warning, keyed by app_id, so the
                    # affected pages can surface it too.
                    st.session_state.setdefault("seed_warnings", {})
                    st.session_state.seed_warnings[result["app_id"]] = result.get("seed_warning")
                    if result.get("seed_warning"):
                        st.warning(f"⚠️ {result['seed_warning']}")
                    st.success(f"✅ Collection complete for **{result['app_name']}**")
                    st.json({
                        "App ID":           result["app_id"],
                        "Country":          country_label(result.get("country", collect_country)),
                        "Reviews saved":    result["reviews_saved"],
                        "Keywords tracked": result["keywords_tracked"],
                    })

with right:
    st.subheader("📂 Load Existing App")
    st.caption("View analysis for an app already in the database.")
    app_id_input = st.text_input("App ID", placeholder="e.g. 324684580")
    # Symmetry with Collect. Loading reads by app_id; live rank lookups then use
    # whichever country the app was collected for (shown once loaded).
    country_selectbox("App Store country", key="load_country")

    if st.button("Load ▶", use_container_width=True):
        if not app_id_input.strip().isdigit():
            st.warning("Please enter a valid numeric App ID.")
        else:
            app_data = api_get(f"/app/{app_id_input.strip()}")
            if app_data:
                st.session_state.app_id   = app_data["app_id"]
                st.session_state.app_name = app_data["name"]
                collected = app_data.get("countries", [])
                # Open on the picked country if that store has data, else the
                # first collected one (pages only offer countries with data).
                load_country = st.session_state.get("load_country")
                st.session_state.active_country = (
                    load_country if load_country in collected
                    else (collected[0] if collected else None)
                )
                labels = ", ".join(country_label(c) for c in collected) or "no data yet"
                st.success(f"✅ Loaded **{app_data['name']}** — collected for: {labels}")

st.divider()

# ── Currently loaded app status ───────────────────────────────────────────────
if st.session_state.app_id:
    app_data = api_get(f"/app/{st.session_state.app_id}")
    if app_data:
        st.subheader(f"Currently viewing: {app_data['name']}")
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("App ID",       app_data["app_id"])
        c2.metric("Avg Rating",   f"{app_data.get('avg_rating', 'N/A')} ⭐")
        c3.metric("Rating Count", f"{app_data.get('rating_count', 0):,}")
        c4.metric("Category",     app_data.get("category", "N/A"))
        c5.metric("Country",      country_label(app_data.get("country", "")))

        st.caption(
            "Live rank lookups (Rankings page) use the App Store country this app "
            "was collected for."
        )
        st.info("Use the sidebar to navigate to Sentiment, Rankings, Competitors, and Recommendations.")
else:
    st.info("Enter an app name above to collect data, or enter an App ID to load existing data.")
