"""Discovers competitor apps via keyword search, gated by an LLM relevance judge."""

from __future__ import annotations

import logging

import config
import database
from analysis import llm_analyst
from collection import scraper

logger = logging.getLogger(__name__)


def calculate_competitor_score(app_data: dict) -> float:
    """
    Score a competitor's strength by popularity and quality.

    Relevance is decided upstream by the LLM judge, so the score only ranks
    already-relevant competitors (popular, well-rated → higher) for tiering.

    Args:
        app_data: App metadata dict with rating_count and avg_rating.

    Returns:
        Float in [0.0, 1.0].
    """
    rating_count = app_data.get("rating_count") or 0
    rating_count_score = min(rating_count / 1_000_000, 1.0)

    avg_rating = app_data.get("avg_rating") or 0
    avg_rating_score = (avg_rating - 1) / 4 if avg_rating else 0.0

    w = config.COMPETITOR_WEIGHTS
    final_score = rating_count_score * w["rating_count"] + avg_rating_score * w["avg_rating"]
    return round(final_score, 4)


def assign_tier(score: float, same_category: bool = True) -> str:
    """
    Split judged competitors into tier1 (big + same-category) and tier2.

    Tier1 is reserved for popular competitors in the target's own category, so a
    huge but off-category app the judge kept (e.g. YouTube for a music app) is
    demoted to tier2 rather than headlining the list.

    Args:
        score:         Popularity score in [0.0, 1.0].
        same_category: Whether the app shares the target's primary category.

    Returns:
        "tier1" if same_category and score >= TIER_1_THRESHOLD, else "tier2".
        Never None — every LLM-judged competitor is kept.
    """
    if same_category and score >= config.TIER_1_THRESHOLD:
        return "tier1"
    return "tier2"


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


def _gather_candidates(
    target_app_id: int,
    target_keywords: list[str],
    country: str = config.DEFAULT_COUNTRY,
) -> list[dict]:
    """
    Collect candidate apps from the seed-keyword searches (deduped, no target).

    Args:
        target_app_id:   The app being analysed (excluded from results).
        target_keywords: Seed keywords defining the competitive space.
        country:         App Store country code to search within.

    Returns:
        List of candidate app metadata dicts.
    """
    candidate_ids: set[int] = set()
    for keyword in target_keywords[: config.COMPETITOR_SEEDS_MAX]:
        for app_id in scraper.fetch_keyword_apps(
            keyword, country=country, limit=config.COMPETITOR_CANDIDATES_PER_SEED
        ):
            if app_id != target_app_id:
                candidate_ids.add(app_id)

    candidates: list[dict] = []
    for app_id in candidate_ids:
        app_data = database.get_app(app_id) or scraper.fetch_app_by_id(app_id, country)
        if app_data:
            candidates.append(app_data)
    return candidates


def discover_competitors(
    target_app_id: int,
    target_keywords: list[str],
    max_depth: int = 1,
    use_llm: bool = True,
    country: str = config.DEFAULT_COUNTRY,
) -> list[dict]:
    """
    Discover competitor apps for a target and gate them by relevance.

    Candidates come from the seed-keyword searches. An LLM judge then keeps only
    genuine competitors (seed-independent, so generic seeds don't leak junk). When
    use_llm is False, it falls back to a same-category filter. Judged competitors
    are scored by popularity, tiered, and saved scoped to the target.

    Args:
        target_app_id:   iTunes ID of the app to find competitors for.
        target_keywords: Seed keywords defining the competitive space.
        max_depth:       Unused (kept for signature compatibility) — the keyword
                         searches already surface the full candidate set.
        use_llm:         Whether to use the LLM relevance judge.
        country:         App Store country code to search within.

    Returns:
        List of competitor dicts sorted by score descending.
    """
    target_data = scraper.fetch_app_by_id(target_app_id, country)
    if target_data is None:
        logger.error(f"Could not fetch target app {target_app_id}")
        return []
    target_category = target_data.get("category")

    candidates = _gather_candidates(target_app_id, target_keywords, country)
    if not candidates:
        return []

    if use_llm:
        keep_ids = llm_analyst.judge_competitors(target_data, candidates, use_llm=True)
        if keep_ids is None:
            raise RuntimeError(
                "AI API quota exhausted (free-tier tokens finished) — competitor "
                "analysis needs it. Please try again in a few minutes."
            )
    else:
        # No-LLM fallback: keep only same-category apps (coarse but avoids
        # cross-category junk without an API call).
        target_category = target_data.get("category")
        keep_ids = {c["app_id"] for c in candidates if c.get("category") == target_category}

    logger.info(f"Competitor judge kept {len(keep_ids)}/{len(candidates)} candidates")

    competitors: list[dict] = []
    for app_data in candidates:
        if app_data["app_id"] not in keep_ids:
            continue
        score = calculate_competitor_score(app_data)
        tier = assign_tier(score, same_category=(app_data.get("category") == target_category))
        app_data["competitor_score"] = score
        app_data["competitor_tier"] = tier
        database.save_app(app_data)
        database.save_competitor(target_app_id, app_data["app_id"], tier, score, country)
        competitors.append(_build_entry(app_data, score, tier))

    return sorted(competitors, key=lambda x: x["score"], reverse=True)
