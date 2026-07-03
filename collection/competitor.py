"""Discovers and scores competitor apps using scored BFS."""

from __future__ import annotations

import logging
from collections import deque

import config
import database
from collection import scraper

logger = logging.getLogger(__name__)


def calculate_competitor_score(
    app_data: dict,
    target_keywords: list[str],
    target_category: str,
) -> float:
    """
    Score how strongly this app competes with the target app.

    Args:
        app_data:        App metadata dict from scraper.
        target_keywords: Keywords the target app targets.
        target_category: Primary genre of the target app.

    Returns:
        Float in [0.0, 1.0] representing competitive strength.
    """
    rating_count = app_data.get("rating_count") or 0
    rating_count_score = min(rating_count / 1_000_000, 1.0)

    avg_rating = app_data.get("avg_rating") or 0
    avg_rating_score = (avg_rating - 1) / 4 if avg_rating else 0.0

    category_match = 1.0 if app_data.get("category") == target_category else 0.0

    keyword_overlap = _compute_keyword_overlap(app_data["app_id"], target_keywords)

    w = config.COMPETITOR_WEIGHTS
    final_score = (
        rating_count_score * w["rating_count"]
        + avg_rating_score * w["avg_rating"]
        + keyword_overlap  * w["keyword_overlap"]
        + category_match   * w["category_match"]
    )
    return round(final_score, 4)


def _compute_keyword_overlap(app_id: int, target_keywords: list[str]) -> float:
    """
    Return fraction of target_keywords for which this app ranks in results.

    Args:
        app_id:          iTunes app ID to probe.
        target_keywords: Keywords to check against.

    Returns:
        Float in [0.0, 1.0], or 0.0 if target_keywords is empty.
    """
    if not target_keywords:
        return 0.0
    ranked = sum(
        1
        for kw in target_keywords
        if scraper.fetch_keyword_ranking(kw, app_id) is not None
    )
    return ranked / len(target_keywords)


def assign_tier(score: float) -> str | None:
    """
    Convert a competitor score to a tier label.

    Args:
        score: Competitor score in [0.0, 1.0].

    Returns:
        "tier1" if score >= TIER_1_THRESHOLD,
        "tier2" if score >= TIER_2_THRESHOLD,
        None otherwise.
    """
    if score >= config.TIER_1_THRESHOLD:
        return "tier1"
    if score >= config.TIER_2_THRESHOLD:
        return "tier2"
    return None


def _build_entry(app_data: dict, score: float, tier: str) -> dict:
    """Return the competitor summary dict appended to the results list."""
    return {
        "app_id":       app_data["app_id"],
        "name":         app_data["name"],
        "score":        score,
        "tier":         tier,
        "category":     app_data["category"],
        "avg_rating":   app_data["avg_rating"],
        "rating_count": app_data["rating_count"],
    }


def _enqueue_neighbours(
    current_id: int,
    target_keywords: list[str],
    depth: int,
    queue: deque,
) -> None:
    """Push keyword-search neighbour app IDs onto the BFS queue."""
    for keyword in target_keywords:
        for app_id in scraper.fetch_keyword_apps(keyword):
            queue.append((app_id, depth + 1))


def discover_competitors(
    target_app_id: int,
    target_keywords: list[str],
    max_depth: int = 2,
) -> list[dict]:
    """
    Perform scored BFS from the target app to discover competitor apps.

    Only apps scoring at or above the tier2 threshold are expanded further.

    Args:
        target_app_id:   iTunes ID of the app to find competitors for.
        target_keywords: Seed keywords defining the competitive space.
        max_depth:       BFS depth limit (default 2).

    Returns:
        List of competitor dicts sorted by score descending.
    """
    target_data = scraper.fetch_app_by_id(target_app_id)
    if target_data is None:
        logger.error(f"Could not fetch target app {target_app_id}")
        return []
    target_category = target_data["category"]

    queue: deque[tuple[int, int]] = deque([(target_app_id, 0)])
    visited: set[int] = set()
    competitors: list[dict] = []

    while queue:
        current_id, depth = queue.popleft()

        if current_id in visited:
            continue
        visited.add(current_id)

        if current_id == target_app_id:
            if depth < max_depth:
                _enqueue_neighbours(current_id, target_keywords, depth, queue)
            continue

        app_data = scraper.fetch_app_by_id(current_id)
        if app_data is None:
            continue

        score = calculate_competitor_score(app_data, target_keywords, target_category)
        tier = assign_tier(score)

        if tier is not None:
            app_data["competitor_score"] = score
            app_data["competitor_tier"] = tier
            database.save_app(app_data)
            database.save_competitor(target_app_id, app_data["app_id"], tier, score)
            competitors.append(_build_entry(app_data, score, tier))
            if depth < max_depth:
                _enqueue_neighbours(current_id, target_keywords, depth, queue)
        else:
            logger.info(f"App {current_id} scored {score:.4f} — below tier2 threshold")

    return sorted(competitors, key=lambda x: x["score"], reverse=True)
