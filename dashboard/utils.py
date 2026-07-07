"""Shared utilities for the Streamlit dashboard."""

from __future__ import annotations

import os
from contextlib import contextmanager

import requests
import streamlit as st

def _get_config(key: str, default: str | None = None) -> str | None:
    """
    Read a config value from Streamlit secrets first, falling back to env vars.

    st.secrets is the guaranteed mechanism on Streamlit Community Cloud;
    os.environ covers local dev via a plain .env file.

    Args:
        key:     Config key to look up.
        default: Value to return if not found anywhere.

    Returns:
        The resolved config value, or default.
    """
    try:
        if key in st.secrets:
            return st.secrets[key]
    except Exception:
        pass
    return os.environ.get(key, default)


API_BASE = _get_config("ASO_API_BASE", "http://localhost:8000")
_API_KEY = _get_config("ASO_API_KEY")
_API_HEADERS = {"X-API-Key": _API_KEY} if _API_KEY else {}


def _error_detail(response: requests.Response) -> str:
    """
    Safely extract an error message from a response, even if the body isn't JSON.

    Args:
        response: The failed HTTP response.

    Returns:
        The 'detail' field if the body is JSON, otherwise the raw text (truncated).
    """
    try:
        return response.json().get("detail", "")
    except ValueError:
        return response.text[:200] or "(empty response — server may have restarted)"


def api_get(endpoint: str, params: dict | None = None) -> dict | list | None:
    """
    Make a GET request to the FastAPI server.

    Args:
        endpoint: URL path starting with /
        params:   Optional query parameters.

    Returns:
        Parsed JSON response, or None on failure.
    """
    try:
        response = requests.get(f"{API_BASE}{endpoint}", params=params, timeout=60)
        response.raise_for_status()
        return response.json()
    except requests.ConnectionError:
        st.error("Cannot connect to FastAPI. Run: uvicorn api.main:app --reload")
        return None
    except requests.HTTPError as e:
        st.error(f"API error {e.response.status_code}: {_error_detail(e.response)}")
        return None
    except Exception as e:
        st.error(f"Unexpected error: {e}")
        return None


def api_post(endpoint: str, params: dict | None = None) -> dict | None:
    """
    Make a POST request to the FastAPI server.

    Args:
        endpoint: URL path starting with /
        params:   Optional query parameters.

    Returns:
        Parsed JSON response, or None on failure.
    """
    try:
        response = requests.post(
            f"{API_BASE}{endpoint}", params=params, headers=_API_HEADERS, timeout=900
        )
        response.raise_for_status()
        return response.json()
    except requests.ConnectionError:
        st.error("Cannot connect to FastAPI. Run: uvicorn api.main:app --reload")
        return None
    except requests.HTTPError as e:
        st.error(f"API error {e.response.status_code}: {_error_detail(e.response)}")
        return None
    except Exception as e:
        st.error(f"Unexpected error: {e}")
        return None


# App Store storefronts offered in the country picker (code → label). The first
# entry is the default and should match config.DEFAULT_COUNTRY on the backend.
COUNTRIES: list[tuple[str, str]] = [
    ("in", "🇮🇳 India"),
    ("us", "🇺🇸 United States"),
    ("gb", "🇬🇧 United Kingdom"),
    ("ca", "🇨🇦 Canada"),
    ("au", "🇦🇺 Australia"),
    ("de", "🇩🇪 Germany"),
    ("fr", "🇫🇷 France"),
    ("es", "🇪🇸 Spain"),
    ("it", "🇮🇹 Italy"),
    ("nl", "🇳🇱 Netherlands"),
    ("br", "🇧🇷 Brazil"),
    ("mx", "🇲🇽 Mexico"),
    ("jp", "🇯🇵 Japan"),
    ("kr", "🇰🇷 South Korea"),
    ("sg", "🇸🇬 Singapore"),
    ("ae", "🇦🇪 United Arab Emirates"),
]

_COUNTRY_LABELS = dict(COUNTRIES)


def country_label(code: str) -> str:
    """Return the display label for a country code, falling back to the code."""
    return _COUNTRY_LABELS.get((code or "").lower(), (code or "").upper())


def country_selectbox(label: str, key: str, default: str | None = None) -> str:
    """
    Render a country picker and return the selected two-letter code.

    Args:
        label:   Label shown above the selectbox.
        key:     Unique Streamlit widget key.
        default: Country code to pre-select (defaults to the first entry).

    Returns:
        The selected two-letter country code.
    """
    codes = [c for c, _ in COUNTRIES]
    index = codes.index(default) if default in codes else 0
    return st.selectbox(
        label,
        codes,
        index=index,
        format_func=country_label,
        key=key,
    )


def active_country_selector(app_id: int, key: str = "active_country") -> str | None:
    """
    Render the active-country picker for a loaded app and return the selection.

    Lists the App Store countries the app has actually been collected for and
    persists the choice in session state (shared key) so every page stays on the
    same country. Returns None when the app has no collected data yet.

    Args:
        app_id: The currently loaded app's ID.
        key:    Session-state / widget key (shared across pages by default).

    Returns:
        The selected two-letter country code, or None if the app has no data.
    """
    data = api_get(f"/app/{app_id}/countries") or {}
    countries = data.get("countries", [])
    if not countries:
        return None
    # Repair the stored selection so it's always a valid option (e.g. after
    # switching to a different app that has different countries).
    if st.session_state.get(key) not in countries:
        st.session_state[key] = countries[0]
    selected = st.selectbox(
        "🌍 Country", countries, format_func=country_label, key=key,
        help="Which App Store's data to view. Collect the app for another "
             "country to add more.",
    )
    st.session_state.country = selected
    return selected


def render_loading_overlay(placeholder, text: str) -> None:
    """
    Render a full-screen centered spinner overlay into a placeholder.

    Used during long operations (e.g. Collect) so the user has clear, centered
    feedback that the app is working. Call placeholder.empty() when done.

    Args:
        placeholder: An st.empty() container to render into.
        text:        Status text shown under the spinner.
    """
    placeholder.markdown(
        f"""
        <div style="position:fixed;top:0;left:0;width:100vw;height:100vh;
                    display:flex;flex-direction:column;align-items:center;
                    justify-content:center;background:rgba(14,17,23,0.6);
                    z-index:99999;">
          <div style="width:72px;height:72px;border:7px solid rgba(255,255,255,0.25);
                      border-top:7px solid #FF4B4B;border-radius:50%;
                      animation:aso-spin 1s linear infinite;"></div>
          <p style="margin-top:20px;color:#fff;font-size:1.05rem;font-weight:600;
                    text-align:center;max-width:80vw;">{text}</p>
        </div>
        <style>@keyframes aso-spin {{ to {{ transform: rotate(360deg); }} }}</style>
        """,
        unsafe_allow_html=True,
    )


@contextmanager
def loading_overlay(text: str = "Loading…"):
    """
    Context manager that shows the centered spinner overlay while its body runs.

    Streamlit streams elements to the browser as the script executes, so the
    overlay is visible during any blocking call inside the `with` block (e.g. a
    slow API request or a Render cold start) and is cleared automatically after.

    Usage:
        with loading_overlay("Loading rankings…"):
            data = api_get("/app/123/rankings")

    Args:
        text: Status text shown under the spinner.
    """
    placeholder = st.empty()
    render_loading_overlay(placeholder, text)
    try:
        yield
    finally:
        placeholder.empty()


def trend_badge(trend: str) -> str:
    """Return a coloured emoji badge for a rank trend label."""
    return {
        "improving": "🟢 Improving",
        "declining": "🔴 Declining",
        "stable":    "🟡 Stable",
        "unknown":   "⚪ Unknown",
    }.get(trend, "⚪ Unknown")


def priority_badge(priority: str) -> str:
    """Return a coloured emoji badge for a recommendation priority."""
    return {
        "high":   "🔴 HIGH",
        "medium": "🟡 MEDIUM",
        "low":    "🟢 LOW",
    }.get(priority, priority.upper())


def seed_warning_banner(app_id: int) -> None:
    """
    Show the LLM seed-fallback warning for an app, if one was recorded.

    Args:
        app_id: The currently loaded app's ID.
    """
    warning = st.session_state.get("seed_warnings", {}).get(app_id)
    if warning:
        st.warning(f"⚠️ {warning}")


def require_app_id() -> int | None:
    """
    Check session state for app_id and show a warning if missing.

    Returns:
        app_id int if set, None otherwise.
    """
    app_id = st.session_state.get("app_id")
    if not app_id:
        st.warning("No app selected. Go to the Home page and load an app first.")
        return None
    return app_id
