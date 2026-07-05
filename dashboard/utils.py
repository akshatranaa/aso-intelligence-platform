"""Shared utilities for the Streamlit dashboard."""

from __future__ import annotations

import os

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
