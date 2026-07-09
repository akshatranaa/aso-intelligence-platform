"""Discovers competitor apps via keyword search, gated by an LLM relevance judge."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

import config
import database
from analysis import llm_analyst
from collection import scraper

logger = logging.getLogger(__name__)


def _is_fresh(iso_timestamp: str, days: int) -> bool:
    """Return True if an ISO timestamp is within the last `days` days."""
    try:
        discovered = datetime.fromisoformat(iso_timestamp)
    except (TypeError, ValueError):
        return False
    return (datetime.now() - discovered) < timedelta(days=days)


def _entry_from_row(comp: dict) -> dict:
    """Shape a stored competitor row like a freshly discovered entry."""
    return {
        "app_id":       comp["app_id"],
        "name":         comp.get("name"),
        "score":        comp.get("competitor_score"),
        "tier":         comp.get("competitor_tier"),
        "category":     comp.get("category"),
        "avg_rating":   comp.get("avg_rating"),
        "rating_count": comp.get("rating_count"),
    }


def has_fresh_competitors(target_app_id: int, country: str) -> bool:
    """
    Return True if competitors for this target+country were discovered recently.

    "Recently" is within config.COMPETITOR_REFRESH_DAYS. Lets the collection flow
    skip both seed generation and competitor discovery on a quick re-collect.
    """
    last = database.get_competitors_last_discovered(target_app_id, country)
    return bool(last) and _is_fresh(last, config.COMPETITOR_REFRESH_DAYS)


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
    max_seeds: int = config.COMPETITOR_SEEDS_MAX,
) -> tuple[list[dict], dict[int, set[str]]]:
    """
    Collect candidate apps from the seed-keyword searches (deduped, no target).

    Args:
        target_app_id:   The app being analysed (excluded from results).
        target_keywords: Seed keywords defining the competitive space.
        country:         App Store country code to search within.
        max_seeds:       How many seed keywords to search (default caps the
                         auto-derived set; the seed editor passes all curated ones).

    Returns:
        (candidates, keyword_map) — the candidate app metadata dicts, and a map
        of candidate app_id → the set of seed keywords whose search surfaced it
        (used to record which keyword owns which competitor).
    """
    keyword_map: dict[int, set[str]] = {}
    for keyword in target_keywords[:max_seeds]:
        for app_id in scraper.fetch_keyword_apps(
            keyword, country=country, limit=config.COMPETITOR_CANDIDATES_PER_SEED
        ):
            if app_id != target_app_id:
                keyword_map.setdefault(app_id, set()).add(keyword)

    candidates: list[dict] = []
    for app_id in keyword_map:
        app_data = database.get_app(app_id) or scraper.fetch_app_by_id(app_id, country)
        if app_data:
            candidates.append(app_data)
    return candidates, keyword_map


def discover_competitors(
    target_app_id: int,
    target_keywords: list[str],
    max_depth: int = 1,
    use_llm: bool = True,
    country: str = config.DEFAULT_COUNTRY,
    force: bool = False,
    max_seeds: int = config.COMPETITOR_SEEDS_MAX,
) -> list[dict]:
    """
    Discover competitor apps for a target and gate them by relevance.

    Candidates come from the seed-keyword searches. An LLM judge then keeps only
    genuine competitors (seed-independent, so generic seeds don't leak junk). When
    use_llm is False, it falls back to a same-category filter. Judged competitors
    are scored by popularity, tiered, and saved scoped to the target.

    If competitors were already discovered for this target+country within the
    last config.COMPETITOR_REFRESH_DAYS days, they are reused as-is (no searches
    or LLM judge) unless force=True — this makes re-collecting an app much cheaper.

    Args:
        target_app_id:   iTunes ID of the app to find competitors for.
        target_keywords: Seed keywords defining the competitive space.
        max_depth:       Unused (kept for signature compatibility) — the keyword
                         searches already surface the full candidate set.
        use_llm:         Whether to use the LLM relevance judge.
        country:         App Store country code to search within.
        force:           Re-discover even if a recent result exists.

    Returns:
        List of competitor dicts sorted by score descending.
    """
    # Reuse a recent discovery for this target+country instead of re-running the
    # searches and LLM judge (competitor sets change slowly).
    if not force and has_fresh_competitors(target_app_id, country):
        existing = database.get_competitors(target_app_id, country)
        logger.info(
            f"Reusing {len(existing)} competitors for {target_app_id} [{country}] "
            f"(discovered < {config.COMPETITOR_REFRESH_DAYS}d ago)"
        )
        return sorted(
            (_entry_from_row(c) for c in existing),
            key=lambda x: x["score"] or 0.0,
            reverse=True,
        )

    target_data = scraper.fetch_app_by_id(target_app_id, country)
    if target_data is None:
        logger.error(f"Could not fetch target app {target_app_id}")
        return []

    candidates, keyword_map = _gather_candidates(
        target_app_id, target_keywords, country, max_seeds
    )
    if not candidates:
        return []

    # A full discovery is authoritative — reset the seed map so it reflects only
    # this run's kept competitors (incremental edits never clear the whole map).
    database.clear_competitor_seed_map(target_app_id, country)
    competitors = _judge_and_save(
        target_app_id, target_data, candidates, keyword_map, country, use_llm
    )
    return sorted(competitors, key=lambda x: x["score"], reverse=True)


def _judge_and_save(
    target_app_id: int,
    target_data: dict,
    candidates: list[dict],
    keyword_map: dict[int, set[str]],
    country: str,
    use_llm: bool,
) -> list[dict]:
    """
    Judge candidates for relevance, save the kept ones, and record seed maps.

    Shared by full discovery and incremental seed additions. For every kept
    competitor it saves the app + competitor row and records a competitor_seeds
    row for each seed keyword that surfaced it.

    Args:
        target_app_id: The target app.
        target_data:   The target's metadata (for the judge + category tiering).
        candidates:    Candidate app metadata dicts.
        keyword_map:   candidate app_id → set of seed keywords that surfaced it.
        country:       App Store country code.
        use_llm:       Whether to use the LLM relevance judge.

    Returns:
        List of kept competitor summary dicts.
    """
    target_category = target_data.get("category")

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
        keep_ids = {c["app_id"] for c in candidates if c.get("category") == target_category}

    logger.info(f"Competitor judge kept {len(keep_ids)}/{len(candidates)} candidates")

    competitors: list[dict] = []
    mappings: list[tuple[str, int]] = []
    for app_data in candidates:
        app_id = app_data["app_id"]
        if app_id not in keep_ids:
            continue
        score = calculate_competitor_score(app_data)
        tier = assign_tier(score, same_category=(app_data.get("category") == target_category))
        app_data["competitor_score"] = score
        app_data["competitor_tier"] = tier
        database.save_app(app_data)
        database.save_competitor(target_app_id, app_id, tier, score, country)
        mappings.extend((kw, app_id) for kw in keyword_map.get(app_id, ()))
        competitors.append(_build_entry(app_data, score, tier))

    database.record_competitor_seeds(target_app_id, country, mappings)
    return competitors


def apply_seed_edit(
    target_app_id: int,
    new_keywords: list[str],
    country: str = config.DEFAULT_COUNTRY,
    use_llm: bool = True,
) -> int:
    """
    Apply an edited seed-keyword set incrementally, then return competitor count.

    Diffs the new seed list against the stored one and only does the minimum work:
      * removed keyword → drop its seed-map rows, then delete competitors that no
        surviving keyword still surfaces (no API calls, no LLM).
      * added keyword   → search + judge that keyword's candidates only, saving
        new competitors and mapping the keyword to every competitor it surfaces.

    The first edit on an app whose seed→competitor map is missing or incomplete
    (e.g. collected before this feature) falls back to one full rebuild, which
    repopulates the map so every later edit stays incremental.

    Args:
        target_app_id: The target app.
        new_keywords:  The complete edited seed keyword list.
        country:       App Store country code.
        use_llm:       Whether to use the LLM relevance judge.

    Returns:
        The number of competitors after the edit.
    """
    old = set(database.get_seed_keywords(target_app_id, country))
    cleaned = list(dict.fromkeys(k.strip() for k in new_keywords if k and k.strip()))
    new = set(cleaned)
    database.set_seed_keywords(target_app_id, country, cleaned)

    if database.competitor_map_needs_rebuild(target_app_id, country):
        logger.info(f"Seed map incomplete for {target_app_id} [{country}] — full rebuild")
        database.delete_all_competitors(target_app_id, country)
        discover_competitors(
            target_app_id, cleaned, country=country, use_llm=use_llm,
            force=True, max_seeds=len(cleaned),
        )
        return len(database.get_competitors(target_app_id, country))

    removed = old - new
    added = new - old

    if removed:
        for keyword in removed:
            database.delete_competitor_seed_keyword(target_app_id, country, keyword)
        orphaned = database.get_orphaned_competitors(target_app_id, country)
        for competitor_app_id in orphaned:
            database.delete_competitor(target_app_id, competitor_app_id, country)
        logger.info(
            f"Removed {len(removed)} seed(s) → dropped {len(orphaned)} competitor(s) "
            f"for {target_app_id} [{country}]"
        )

    if added:
        _add_seed_keywords(target_app_id, sorted(added), country, use_llm)

    return len(database.get_competitors(target_app_id, country))


def _add_seed_keywords(
    target_app_id: int, keywords: list[str], country: str, use_llm: bool
) -> None:
    """
    Discover and save competitors for newly-added seed keywords only.

    Searches just the added keywords, judges their candidates, and saves the
    survivors — mapping each added keyword to every competitor it surfaces
    (including ones already kept from other seeds). Existing competitors are
    left untouched.

    Args:
        target_app_id: The target app.
        keywords:      The newly-added seed keywords.
        country:       App Store country code.
        use_llm:       Whether to use the LLM relevance judge.
    """
    target_data = scraper.fetch_app_by_id(target_app_id, country)
    if target_data is None:
        logger.error(f"Could not fetch target app {target_app_id} for seed add")
        return
    candidates, keyword_map = _gather_candidates(
        target_app_id, keywords, country, max_seeds=len(keywords)
    )
    if not candidates:
        logger.info(f"Added seed(s) surfaced no candidates for {target_app_id}")
        return
    kept = _judge_and_save(
        target_app_id, target_data, candidates, keyword_map, country, use_llm
    )
    logger.info(
        f"Added {len(keywords)} seed(s) → {len(kept)} competitor mapping(s) "
        f"for {target_app_id} [{country}]"
    )
