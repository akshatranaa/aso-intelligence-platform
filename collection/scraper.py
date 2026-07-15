"""Fetches app metadata, reviews, and keyword data from Apple's free public APIs."""

from __future__ import annotations

import plistlib
import time
import logging

import httpx

import config

logger = logging.getLogger(__name__)

client = httpx.Client(timeout=30.0)


def _rate_limit() -> None:
    """Pause between API requests to avoid hammering Apple's servers."""
    time.sleep(config.RATE_LIMIT_SECONDS)


def _parse_app_fields(result: dict, country: str) -> dict:
    """
    Map a single iTunes API result dict to the canonical app field dict.

    Args:
        result:  One entry from the iTunes API results list.
        country: Two-letter country code to store on the record.

    Returns:
        Dict with keys matching the apps table column names.
    """
    return {
        "app_id":         result.get("trackId"),
        "name":           result.get("trackName"),
        "description":    result.get("description"),
        "release_notes":  result.get("releaseNotes"),
        "category":       result.get("primaryGenreName"),
        "genres":         result.get("genres", []),
        "avg_rating":     result.get("averageUserRating"),
        "rating_count":   result.get("userRatingCount"),
        "price":          result.get("price"),
        "seller_name":    result.get("sellerName"),
        "bundle_id":      result.get("bundleId"),
        "min_os_version": result.get("minimumOsVersion"),
        "version":        result.get("version"),
        "country":        country,
    }


def search_apps(
    term: str, country: str = config.DEFAULT_COUNTRY, limit: int = 8
) -> list[dict]:
    """
    Search iTunes for apps by name, returning lightweight suggestions.

    Used for the collect-form autocomplete — returns just enough to show a
    picker (name, id, category, icon), not the full metadata.

    Args:
        term:    Partial or full app name.
        country: Two-letter App Store country code.
        limit:   Maximum suggestions to return.

    Returns:
        List of {app_id, name, category, seller, artwork} dicts (may be empty).
    """
    url = config.ITUNES_SEARCH_URL
    params = {"term": term, "entity": "software", "country": country, "limit": limit}
    try:
        response = client.get(url, params=params)
        response.raise_for_status()
        results = response.json().get("results", [])
        return [
            {
                "app_id":   r.get("trackId"),
                "name":     r.get("trackName"),
                "category": r.get("primaryGenreName"),
                "seller":   r.get("sellerName"),
                "artwork":  r.get("artworkUrl60") or r.get("artworkUrl100"),
            }
            for r in results
            if r.get("trackId")
        ]
    except httpx.TimeoutException:
        logger.error(f"Timeout fetching: {url}")
        return []
    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP {e.response.status_code} for: {url}")
        return []
    except Exception as e:
        logger.error(f"Unexpected error fetching {url}: {e}")
        return []
    finally:
        _rate_limit()


def fetch_app_metadata(app_name: str, country: str = config.DEFAULT_COUNTRY) -> dict | None:
    """
    Search iTunes for an app by name and return its metadata.

    Args:
        app_name: App name to search for, e.g. "Spotify".
        country:  Two-letter App Store country code.

    Returns:
        Dict with app metadata fields, or None if not found or on error.
    """
    url = config.ITUNES_SEARCH_URL
    params = {
        "term":    app_name,
        "entity":  "software",
        "country": country,
        "limit":   1,
    }
    try:
        response = client.get(url, params=params)
        response.raise_for_status()
        data = response.json()
        results = data.get("results", [])
        if not results:
            logger.warning(f"No results found for app name: {app_name}")
            return None
        return _parse_app_fields(results[0], country)
    except httpx.TimeoutException:
        logger.error(f"Timeout fetching: {url}")
        return None
    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP {e.response.status_code} for: {url}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error fetching {url}: {e}")
        return None
    finally:
        _rate_limit()


def fetch_app_by_id(app_id: int, country: str = config.DEFAULT_COUNTRY) -> dict | None:
    """
    Fetch a specific app by its iTunes numeric ID.

    More precise than search — use this for competitor fetching.

    Args:
        app_id:  iTunes numeric app ID.
        country: Two-letter App Store country code.

    Returns:
        Dict with app metadata fields, or None if not found or on error.
    """
    url = config.ITUNES_LOOKUP_URL
    params = {
        "id":      app_id,
        "country": country,
    }
    try:
        response = client.get(url, params=params)
        response.raise_for_status()
        data = response.json()
        results = data.get("results", [])
        if not results:
            logger.warning(f"No app found for id: {app_id}")
            return None
        return _parse_app_fields(results[0], country)
    except httpx.TimeoutException:
        logger.error(f"Timeout fetching: {url}")
        return None
    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP {e.response.status_code} for: {url}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error fetching {url}: {e}")
        return None
    finally:
        _rate_limit()


def fetch_reviews(
    app_id: int, country: str = config.DEFAULT_COUNTRY
) -> tuple[list[dict], bool]:
    """
    Fetch the most recent reviews for an app from the iTunes RSS feed.

    Retries up to config.REVIEWS_FETCH_ATTEMPTS times on failure — Apple's
    feed occasionally errors on a single request, or returns a "successful"
    but suspiciously empty body (soft throttling: 200 OK, zero entries — not
    even the one entry that always describes the app itself). A genuinely
    review-less app still returns that one description entry, so a completely
    empty body is treated as a failed attempt rather than "no reviews".

    Args:
        app_id:  iTunes numeric app ID.
        country: Two-letter App Store country code.

    Returns:
        (reviews, fetch_failed). reviews is a list of dicts with keys:
        review_text, rating, review_date, author — empty if the app has none,
        or if every attempt failed. fetch_failed is True only when every
        attempt errored or came back empty, so the caller can tell "no
        reviews" apart from "the fetch didn't work" instead of both looking
        like an empty list.
    """
    url = config.ITUNES_REVIEWS_URL.format(country=country, app_id=app_id)
    for attempt in range(1, config.REVIEWS_FETCH_ATTEMPTS + 1):
        try:
            response = client.get(url)
            response.raise_for_status()
            data = response.json()
            entries = data.get("feed", {}).get("entry", [])
            if not entries:
                # Zero entries (not even the app-description one) looks like
                # soft throttling, not a genuine "no reviews" state — retry it.
                logger.error(
                    f"Empty feed body (attempt {attempt}), likely throttled: {url}"
                )
                continue
            # First entry describes the app itself — skip it
            review_entries = entries[1:] if len(entries) > 1 else []
            reviews = []
            for entry in review_entries:
                reviews.append({
                    "review_text":  entry.get("content", {}).get("label"),
                    "rating":       int(entry.get("im:rating", {}).get("label", 0)),
                    "review_date":  entry.get("updated", {}).get("label"),
                    "author":       entry.get("author", {}).get("name", {}).get("label"),
                })
            return reviews, False
        except httpx.TimeoutException:
            logger.error(f"Timeout fetching (attempt {attempt}): {url}")
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP {e.response.status_code} (attempt {attempt}): {url}")
        except Exception as e:
            logger.error(f"Unexpected error (attempt {attempt}) fetching {url}: {e}")
        finally:
            _rate_limit()
    logger.error(
        f"Giving up on reviews for app {app_id} [{country}] after "
        f"{config.REVIEWS_FETCH_ATTEMPTS} attempts"
    )
    return [], True


def fetch_keyword_ranking(
    keyword: str,
    target_app_id: int,
    country: str = config.DEFAULT_COUNTRY,
) -> int | None:
    """
    Find the position of the target app in App Store search results for a keyword.

    Args:
        keyword:       Search term to look up.
        target_app_id: iTunes numeric ID of the app to locate.
        country:       Two-letter App Store country code.

    Returns:
        Rank position (1-indexed; 1 = top result), or None if the app is not
        found in the top RANKING_SEARCH_LIMIT results.
    """
    url = config.ITUNES_SEARCH_URL
    params = {
        "term":    keyword,
        "entity":  "software",
        "country": country,
        "limit":   config.RANKING_SEARCH_LIMIT,
    }
    try:
        response = client.get(url, params=params)
        response.raise_for_status()
        data = response.json()
        for index, result in enumerate(data.get("results", [])):
            if result.get("trackId") == target_app_id:
                return index + 1
        return None
    except httpx.TimeoutException:
        logger.error(f"Timeout fetching: {url}")
        return None
    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP {e.response.status_code} for: {url}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error fetching {url}: {e}")
        return None
    finally:
        _rate_limit()


def fetch_keyword_apps(
    keyword: str,
    country: str = config.DEFAULT_COUNTRY,
    limit: int = 20,
) -> list[int]:
    """
    Return the app IDs of the top results for a keyword search.

    Used by competitor.py for BFS neighbour discovery.

    Args:
        keyword: Search term to look up.
        country: Two-letter App Store country code.
        limit:   Maximum number of app IDs to return.

    Returns:
        List of iTunes numeric app IDs from the top results.
        Returns an empty list if the request fails.
    """
    url = config.ITUNES_SEARCH_URL
    params = {
        "term":    keyword,
        "entity":  "software",
        "country": country,
        "limit":   limit,
    }
    try:
        response = client.get(url, params=params)
        response.raise_for_status()
        data = response.json()
        return [
            result["trackId"]
            for result in data.get("results", [])
            if "trackId" in result
        ]
    except httpx.TimeoutException:
        logger.error(f"Timeout fetching: {url}")
        return []
    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP {e.response.status_code} for: {url}")
        return []
    except Exception as e:
        logger.error(f"Unexpected error fetching {url}: {e}")
        return []
    finally:
        _rate_limit()


def fetch_keyword_suggestions(
    term: str,
    country: str = config.DEFAULT_COUNTRY,
) -> list[str]:
    """
    Fetch App Store autocomplete suggestions for a search term.

    These are real keywords users type — the primary keyword discovery source.
    The endpoint returns Apple plist XML, parsed with plistlib.

    Args:
        term:    Partial search term to expand.
        country: Two-letter App Store country code.

    Returns:
        List of suggestion strings, or [] on any failure.
    """
    url = config.ITUNES_AUTOCOMPLETE_URL
    params = {"q": term, "media": "software", "country": country}
    headers = {"User-Agent": "iTunes/12.12.9 (Macintosh; OS X 10.15.7) AppleWebKit/606.1"}
    try:
        response = client.get(url, params=params, headers=headers)
        response.raise_for_status()
        data = plistlib.loads(response.content)
        hints = data.get("hints", [])
        return [
            h["term"] if isinstance(h, dict) else h
            for h in hints
            if isinstance(h, str) or (isinstance(h, dict) and "term" in h)
        ]
    except httpx.TimeoutException:
        logger.error(f"Timeout fetching: {url}")
        return []
    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP {e.response.status_code} for: {url}")
        return []
    except Exception as e:
        logger.error(f"Unexpected error fetching {url}: {e}")
        return []
    finally:
        _rate_limit()
