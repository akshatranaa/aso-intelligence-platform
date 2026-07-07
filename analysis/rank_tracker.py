"""Daily ranking snapshots, velocity computation, and significant change detection."""

from __future__ import annotations

import logging
from datetime import date

import config
import database
from collection import scraper

logger = logging.getLogger(__name__)


def take_snapshot(
    app_id: int, keywords: list[str], country: str = config.DEFAULT_COUNTRY
) -> dict:
    """
    Fetch and store today's rank for each keyword.

    Args:
        app_id:   iTunes app ID of the target app.
        keywords: List of keyword strings to snapshot.
        country:  App Store country code to search within.

    Returns:
        Dict mapping keyword → rank (None if app not in top results).
    """
    today = str(date.today())
    snapshot = {}
    for keyword in keywords:
        rank = scraper.fetch_keyword_ranking(keyword, app_id, country)
        # Persist every keyword — a NULL-rank row keeps a tracked-but-unranked
        # keyword visible ("Unranked") instead of silently disappearing.
        database.save_ranking(app_id, keyword, rank, today)
        snapshot[keyword] = rank
        logger.info(f"Snapshot '{keyword}': rank={rank}")
    return snapshot


def track_keyword(
    app_id: int, keyword: str, country: str = config.DEFAULT_COUNTRY
) -> list[dict]:
    """
    Snapshot a single (typically user-added) keyword and return the summary.

    Args:
        app_id:  iTunes app ID of the target app.
        keyword: Keyword to start tracking.
        country: App Store country code to search within.

    Returns:
        The refreshed ranking summary for the app (one row per tracked keyword).
    """
    take_snapshot(app_id, [keyword], country)
    return get_ranking_summary(app_id)


def refresh_rankings(app_id: int, country: str = config.DEFAULT_COUNTRY) -> list[dict]:
    """
    Re-snapshot every keyword already tracked for an app, without a full collect.

    This is the rankings-only slice of a collection run (no metadata, competitor,
    review, or sentiment work), so it returns quickly enough to run synchronously.

    Args:
        app_id:  iTunes app ID of the target app.
        country: App Store country code to search within.

    Returns:
        The refreshed ranking summary after re-snapshotting and recomputing velocity.
    """
    tracked = list(dict.fromkeys(
        row["keyword"] for row in database.get_all_rankings(app_id)
    ))
    take_snapshot(app_id, tracked, country)
    compute_all_velocities(app_id)
    logger.info(f"Refreshed rankings for {len(tracked)} keywords (app {app_id})")
    return get_ranking_summary(app_id)


def compute_velocity(app_id: int, keyword: str) -> float | None:
    """
    Compute the average daily rank change for one keyword over the recent window.

    Negative velocity means climbing (rank number decreasing = good).
    Positive velocity means dropping (rank number increasing = bad).
    Writes the result back to the most recent ranking row.

    Args:
        app_id:  iTunes app ID.
        keyword: Keyword string.

    Returns:
        Mean rank delta over the last RANK_VELOCITY_DAYS days,
        or None if fewer than MIN_DAYS_FOR_VELOCITY rows exist.
    """
    # Only ranked snapshots have a numeric position; skip NULL-rank rows
    # (keyword tracked but app not in the top results that day).
    rows = [r for r in database.get_rankings(app_id, keyword) if r["rank"] is not None]
    if len(rows) < config.MIN_DAYS_FOR_VELOCITY:
        return None

    recent = rows[-config.RANK_VELOCITY_DAYS:]
    deltas = [
        recent[i]["rank"] - recent[i - 1]["rank"]
        for i in range(1, len(recent))
    ]
    velocity = sum(deltas) / len(deltas)

    database.update_rank_velocity(recent[-1]["id"], velocity)
    logger.info(f"Velocity '{keyword}': {velocity:.3f} positions/day")
    return velocity


def compute_all_velocities(app_id: int) -> dict:
    """
    Compute velocity for every keyword tracked for this app.

    Args:
        app_id: iTunes app ID.

    Returns:
        Dict mapping keyword → velocity (None if insufficient data).
    """
    all_rows = database.get_all_rankings(app_id)
    keywords = {row["keyword"] for row in all_rows}
    velocities = {kw: compute_velocity(app_id, kw) for kw in keywords}
    logger.info(f"Computed velocities for {len(velocities)} keywords")
    return velocities


def detect_significant_changes(app_id: int, keywords: list[str]) -> list[dict]:
    """
    Find keywords where rank shifted by more than RANK_ALERT_THRESHOLD positions.

    Args:
        app_id:   iTunes app ID.
        keywords: List of keyword strings to check.

    Returns:
        List of alert dicts for keywords with significant rank changes.
    """
    alerts = []
    for keyword in keywords:
        rows = database.get_rankings(app_id, keyword)
        if not rows:
            continue
        latest = rows[-1]
        delta = latest["rank_delta"]
        if delta is None or abs(delta) <= config.RANK_ALERT_THRESHOLD:
            continue
        old_rank = latest["rank"] - delta
        alerts.append({
            "keyword":   keyword,
            "old_rank":  old_rank,
            "new_rank":  latest["rank"],
            "delta":     delta,
            "direction": "up" if delta < 0 else "down",
            "velocity":  latest["rank_velocity"],
        })
        logger.warning(
            f"Significant change '{keyword}': {old_rank} → {latest['rank']} "
            f"({'+' if delta > 0 else ''}{delta})"
        )
    return alerts


def compare_competitor_ranks(
    app_id: int,
    keyword: str,
    max_competitors: int = config.RANK_COMPETITOR_COMPARE_MAX,
    country: str = config.DEFAULT_COUNTRY,
) -> dict:
    """
    Compare the target's rank for a keyword against its top competitors.

    Live iTunes lookups — one for the target plus one per competitor (capped at
    max_competitors, highest competitor_score first). Rate-limited, so ~1+N seconds.

    Args:
        app_id:          iTunes app ID of the target app.
        keyword:         Keyword to compare ranks for.
        max_competitors: Maximum number of competitors to look up.
        country:         App Store country code to search within.

    Returns:
        Dict with keyword, the target {name, rank}, and a competitors list of
        {name, app_id, rank} sorted by rank ascending (unranked/None last).
    """
    target_app = database.get_app(app_id)
    target_name = target_app["name"] if target_app else str(app_id)
    target_rank = scraper.fetch_keyword_ranking(keyword, app_id, country)

    competitors = sorted(
        database.get_competitors(app_id),
        key=lambda c: c.get("competitor_score") or 0.0,
        reverse=True,
    )[:max_competitors]

    comp_results = []
    for comp in competitors:
        rank = scraper.fetch_keyword_ranking(keyword, comp["app_id"], country)
        comp_results.append({
            "name":   comp.get("name", str(comp["app_id"])),
            "app_id": comp["app_id"],
            "rank":   rank,
        })

    # Sort by rank, pushing unranked (None) to the end.
    comp_results.sort(key=lambda c: (c["rank"] is None, c["rank"] or 0))
    logger.info(
        f"Compared '{keyword}' ranks: target={target_rank}, "
        f"{len(comp_results)} competitors"
    )
    return {
        "keyword":     keyword,
        "target":      {"name": target_name, "rank": target_rank},
        "competitors": comp_results,
    }


def get_ranking_summary(app_id: int) -> list[dict]:
    """
    Return the latest rank, delta, velocity, and trend for every tracked keyword.

    Args:
        app_id: iTunes app ID.

    Returns:
        List of summary dicts, one per tracked keyword.
    """
    all_rows = database.get_all_rankings(app_id)

    latest_by_keyword: dict[str, dict] = {}
    for row in all_rows:
        latest_by_keyword[row["keyword"]] = row

    summary = []
    for keyword, row in latest_by_keyword.items():
        velocity = row.get("rank_velocity")
        if velocity is None:
            trend = "unknown"
        elif velocity < -0.5:
            trend = "improving"
        elif velocity > 0.5:
            trend = "declining"
        else:
            trend = "stable"
        summary.append({
            "keyword":  keyword,
            "rank":     row["rank"],
            "delta":    row["rank_delta"],
            "velocity": velocity,
            "trend":    trend,
        })
    return summary
