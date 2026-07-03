"""Autocomplete-based keyword discovery, scoring, gap analysis, and LLM narrative generation."""

from __future__ import annotations

import heapq
import logging
import string
from datetime import datetime

import config
import database
from analysis import llm_analyst
from collection import scraper

logger = logging.getLogger(__name__)


def derive_seed_keywords(app_data: dict) -> list[str]:
    """
    Build seed search terms from a target app's own name and category.

    Generalises the pipeline to any app (VPN, game, fitness, etc.) instead
    of assuming music-specific seeds. Shared by competitor discovery, rank
    tracking, and keyword discovery so there is a single source of truth.

    Args:
        app_data: App metadata dict with at least 'name' and 'category'.

    Returns:
        Deduplicated list of lowercase seed search terms.
    """
    name = app_data.get("name", "").split(":")[0].strip(string.punctuation).strip().lower()
    category = (app_data.get("category") or "").strip().lower()

    seeds = []
    if name:
        seeds.append(name)
    if category:
        seeds.append(category)
        seeds.append(f"{category} app")
    return [s for s in dict.fromkeys(seeds) if s]


def run_keyword_analysis(app_id: int, use_llm: bool = True) -> dict:
    """
    Master function — run the full keyword pipeline for one app.

    Args:
        app_id:  iTunes app ID of the target app.
        use_llm: Whether to generate an LLM strategy narrative.

    Returns:
        Dict with top_keywords, gaps, and narrative keys.
    """
    target_app = database.get_app(app_id)
    all_apps   = database.get_all_apps()
    candidates = extract_keywords(target_app, all_apps)
    scored     = score_keywords(candidates, app_id)
    gaps       = find_keyword_gaps(app_id)
    _save_keywords(scored + gaps, app_id)
    top_k      = get_top_k_keywords(app_id)
    narrative  = llm_analyst.generate_keyword_narrative(
        top_k + gaps, target_app["name"], use_llm=use_llm
    )
    return {"top_keywords": top_k, "gaps": gaps, "narrative": narrative}


def extract_keywords(target_app: dict, all_apps: list[dict]) -> list[str]:
    """
    Discover candidate keywords using Apple's own autocomplete API.
    All candidates are real terms users actually search for.
    """
    candidates = set()

    # Source 1: autocomplete on seed terms derived from the target app itself
    for seed in derive_seed_keywords(target_app):
        suggestions = scraper.fetch_keyword_suggestions(seed)
        candidates.update(suggestions)

    # Source 2: alphabet expansion on app name
    base = target_app["name"].lower().split()[0].strip(string.punctuation)
    for letter in "abcdefghijklmnopqrstuvwxyz":
        suggestions = scraper.fetch_keyword_suggestions(f"{base} {letter}")
        candidates.update(suggestions)

    # Source 3: competitor name expansion (tier1 only)
    tier1 = [a for a in all_apps if a.get("competitor_tier") == "tier1"]
    for comp in tier1[:5]:
        base_name = comp["name"].lower().split()[0].strip(string.punctuation)
        suggestions = scraper.fetch_keyword_suggestions(base_name)
        candidates.update(suggestions)

    logger.info(f"Discovered {len(candidates)} real keyword candidates")
    return list(candidates)

def score_keywords(keywords: list[str], app_id: int) -> list[dict]:
    """
    Score each candidate keyword for volume, difficulty, and opportunity.

    Makes iTunes API calls — this is the slow part of the pipeline.

    Args:
        keywords: List of keyword strings to score.
        app_id:   iTunes app ID used to look up current ranking.

    Returns:
        List of scored keyword dicts.
    """
    results = []
    for keyword in keywords:
        top_ids    = scraper.fetch_keyword_apps(keyword, limit=10)
        top_apps   = _fetch_apps(top_ids)
        volume     = _estimate_volume(top_apps)
        difficulty = _estimate_difficulty(top_apps)
        rank       = scraper.fetch_keyword_ranking(keyword, app_id)
        relevance  = _tfidf_relevance(keyword, top_apps)
        opportunity = _calculate_opportunity(volume, difficulty, relevance)
        results.append({
            "keyword":           keyword,
            "proxy_volume":      volume,
            "proxy_difficulty":  difficulty,
            "proxy_opportunity": opportunity,
            "current_rank":      rank,
            "source":            "autocomplete",
            "is_gap_keyword":    0,
            "gap_competitor":    None,
        })
        logger.info(f"Scored '{keyword}': vol={volume:.3f} diff={difficulty:.3f} opp={opportunity:.3f}")
    return results


def _fetch_apps(app_ids: list[int]) -> list[dict]:
    """
    Return app dicts for a list of IDs, hitting DB first to avoid API calls.

    Args:
        app_ids: List of iTunes app IDs to fetch.

    Returns:
        List of app metadata dicts (skips IDs that can't be fetched).
    """
    apps = []
    for app_id in app_ids:
        app = database.get_app(app_id) or scraper.fetch_app_by_id(app_id)
        if app:
            apps.append(app)
    return apps


def _tfidf_relevance(keyword: str, top_apps: list[dict]) -> float:
    """
    Proxy relevance: fraction of top-ranking apps whose description contains the keyword.

    Args:
        keyword:  Keyword string.
        top_apps: App dicts of top search results for this keyword.

    Returns:
        Float in [0.0, 1.0].
    """
    if not top_apps:
        return 0.0
    hits = sum(
        1 for a in top_apps
        if keyword.lower() in (a.get("description") or "").lower()
    )
    return hits / len(top_apps)


def _estimate_volume(top_apps: list[dict]) -> float:
    """
    Estimate search volume from the rating counts of top-ranking apps.

    Args:
        top_apps: App dicts for the top results of a keyword search.

    Returns:
        Float in [0.0, 1.0].
    """
    if not top_apps:
        return 0.0
    avg_count = sum(a.get("rating_count") or 0 for a in top_apps) / len(top_apps)
    return min(avg_count / 5_000_000, 1.0)


def _estimate_difficulty(top_apps: list[dict]) -> float:
    """
    Estimate keyword difficulty from the strength of top-ranking apps.

    Args:
        top_apps: App dicts for the top results of a keyword search (up to 10).

    Returns:
        Float in [0.0, 1.0].
    """
    weighted_score = 0.0
    for i, app in enumerate(top_apps[:10], start=1):
        position_weight = (11 - i) / 10
        rating_count    = app.get("rating_count") or 0
        avg_rating      = app.get("avg_rating") or 0.0
        app_strength    = min(rating_count / 2_000_000, 1.0) * (avg_rating / 5.0)
        weighted_score += app_strength * position_weight
    return min(weighted_score / 5.0, 1.0)


def _calculate_opportunity(volume: float, difficulty: float, relevance: float) -> float:
    """
    Combine volume, difficulty, and relevance into one opportunity score.

    Args:
        volume:     Estimated search volume (0–1).
        difficulty: Estimated keyword difficulty (0–1).
        relevance:  Keyword relevance to target app (0–1).

    Returns:
        Float clamped to [0.0, 1.0].
    """
    w = config.PROXY_OPPORTUNITY_WEIGHTS
    score = (
        volume     * w["volume"]
        + relevance  * w["relevance"]
        - difficulty * w["difficulty"]
    )
    return max(0.0, min(1.0, score))


def find_keyword_gaps(app_id: int) -> list[dict]:
    """
    Find keywords competitors rank for that the target app does not.

    Args:
        app_id: iTunes app ID of the target app.

    Returns:
        List of scored gap keyword dicts sorted by opportunity descending.
    """
    target_keywords = {
        row["keyword"] for row in database.get_all_rankings(app_id)
    }
    competitor_ids = [
        app["app_id"] for app in database.get_all_apps() if not app["is_target_app"]
    ]

    gap_map: dict[str, dict] = {}
    for comp_id in competitor_ids:
        comp_app      = database.get_app(comp_id)
        comp_keywords = {row["keyword"] for row in database.get_all_rankings(comp_id)}
        new_gaps        = comp_keywords - target_keywords
        scored_gaps     = score_keywords(list(new_gaps), app_id)
        for kw_dict in scored_gaps:
            kw = kw_dict["keyword"]
            if kw not in gap_map or kw_dict["proxy_opportunity"] > gap_map[kw]["proxy_opportunity"]:
                kw_dict["is_gap_keyword"] = 1
                kw_dict["gap_competitor"] = comp_app["name"] if comp_app else str(comp_id)
                gap_map[kw] = kw_dict

    return sorted(gap_map.values(), key=lambda x: x["proxy_opportunity"], reverse=True)


def get_top_k_keywords(
    app_id: int, k: int = config.TOP_K_KEYWORDS
) -> list[dict]:
    """
    Return the top K keywords by opportunity score using a max-heap.

    Args:
        app_id: iTunes app ID.
        k:      Number of keywords to return.

    Returns:
        List of up to k keyword dicts sorted by proxy_opportunity descending.
    """
    all_keywords = database.get_keywords(app_id)
    heap = [
        (-kw["proxy_opportunity"], i, kw)
        for i, kw in enumerate(all_keywords)
    ]
    heapq.heapify(heap)
    return [heapq.heappop(heap)[2] for _ in range(min(k, len(heap)))]


def _save_keywords(keywords: list[dict], app_id: int) -> None:
    """
    Save scored keywords to the keywords table (insert or replace).

    Args:
        keywords: List of scored keyword dicts from score_keywords / find_keyword_gaps.
        app_id:   iTunes app ID the keywords belong to.
    """
    now = datetime.now().isoformat()
    for kw in keywords:
        database.save_keyword({
            "app_id":               app_id,
            "keyword":              kw["keyword"],
            "proxy_volume":         kw.get("proxy_volume"),
            "proxy_difficulty":     kw.get("proxy_difficulty"),
            "proxy_opportunity":    kw.get("proxy_opportunity"),
            "confirmed_volume":     None,
            "confirmed_conversion": None,
            "confirmed_cpi":        None,
            "revised_opportunity":  None,
            "keyword_bucket":       None,
            "is_hidden_gem":        0,
            "is_gap_keyword":       kw.get("is_gap_keyword", 0),
            "gap_competitor":       kw.get("gap_competitor"),
            "source":               kw.get("source", "autocomplete"),
            "created_at":           now,
            "updated_at":           now,
        })
    logger.info(f"Saved {len(keywords)} keywords for app {app_id}")
