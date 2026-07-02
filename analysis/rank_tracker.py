"""Daily ranking snapshots, velocity computation, and significant change detection."""

from __future__ import annotations

import logging
from datetime import date

import config
import database
from collection import scraper

logger = logging.getLogger(__name__)


def take_snapshot(app_id: int, keywords: list[str]) -> dict:
    """
    Fetch and store today's rank for each keyword.

    Args:
        app_id:   iTunes app ID of the target app.
        keywords: List of keyword strings to snapshot.

    Returns:
        Dict mapping keyword → rank (None if app not in top results).
    """
    today = str(date.today())
    snapshot = {}
    for keyword in keywords:
        rank = scraper.fetch_keyword_ranking(keyword, app_id)
        if rank is not None:
            database.save_ranking(app_id, keyword, rank, today)
        snapshot[keyword] = rank
        logger.info(f"Snapshot '{keyword}': rank={rank}")
    return snapshot


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
    rows = database.get_rankings(app_id, keyword)
    if len(rows) < config.MIN_DAYS_FOR_VELOCITY:
        return None

    recent = rows[-config.RANK_VELOCITY_DAYS:]
    deltas = [
        recent[i]["rank"] - recent[i - 1]["rank"]
        for i in range(1, len(recent))
    ]
    velocity = sum(deltas) / len(deltas)

    with database.get_connection() as conn:
        conn.execute(
            "UPDATE rankings SET rank_velocity = ? WHERE id = ?",
            (velocity, recent[-1]["id"]),
        )
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
