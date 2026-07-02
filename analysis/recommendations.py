"""Decision engine — synthesises all analysis into actionable ASO recommendations."""

from __future__ import annotations

import logging
from datetime import datetime

import config
import database
from analysis import llm_analyst, rank_tracker, sentiment

logger = logging.getLogger(__name__)


def generate_recommendations(app_id: int, use_llm: bool = True) -> dict:
    """
    Master function — produce a full recommendation report for one app.

    Args:
        app_id:  iTunes app ID of the target app.
        use_llm: Whether to call the LLM for competitor comparison and description rewrite.

    Returns:
        Dict with keyword, sentiment, competitor, and description recommendations.
    """
    target_app = database.get_app(app_id)
    if not target_app:
        logger.error(f"No app found for app_id {app_id}")
        return {}

    keyword_rec      = _get_keyword_recommendations(app_id)
    sentiment_rec    = _get_sentiment_recommendations(app_id, use_llm=use_llm)
    competitor_rec   = _get_competitor_recommendations(app_id, use_llm=use_llm)
    description      = _suggest_description(app_id, use_llm=use_llm)
    priority_actions = _build_priority_actions(keyword_rec, sentiment_rec, competitor_rec)

    logger.info(f"Generated recommendations for {target_app['name']}")
    return {
        "app_id":                     app_id,
        "app_name":                   target_app["name"],
        "generated_at":               datetime.now().isoformat(),
        "keyword_recommendations":    keyword_rec,
        "sentiment_recommendations":  sentiment_rec,
        "competitor_recommendations": competitor_rec,
        "description_recommendation": description,
        "priority_actions":           priority_actions,
    }


def _best_score(kw: dict) -> float:
    """
    Return the best available opportunity score for a keyword.

    Prefers confirmed (Search Ads) score over proxy score.

    Args:
        kw: Keyword dict from database.

    Returns:
        Float opportunity score in [0.0, 1.0].
    """
    return kw.get("revised_opportunity") or kw.get("proxy_opportunity") or 0.0


def _get_keyword_recommendations(app_id: int) -> dict:
    """
    Classify keywords into actionable buckets based on opportunity score and rank.

    Args:
        app_id: iTunes app ID.

    Returns:
        Dict with prioritise, defend, target_gaps, and drop keyword lists.
    """
    keywords = database.get_keywords(app_id)
    ranking_summary = {
        r["keyword"]: r for r in rank_tracker.get_ranking_summary(app_id)
    }

    prioritise, defend, target_gaps, drop = [], [], [], []

    for kw in keywords:
        score     = _best_score(kw)
        keyword   = kw["keyword"]
        rank_info = ranking_summary.get(keyword, {})
        rank      = rank_info.get("rank")
        trend     = rank_info.get("trend", "unknown")

        if kw.get("is_gap_keyword"):
            target_gaps.append({**kw, "opportunity_score": score})
        elif score >= 0.7 and rank is None:
            prioritise.append({**kw, "opportunity_score": score})
        elif rank and rank <= 10 and trend in ("stable", "improving"):
            defend.append({**kw, "opportunity_score": score, "rank": rank, "trend": trend})
        elif score < 0.3:
            drop.append({**kw, "opportunity_score": score})

    return {
        "prioritise":  sorted(prioritise,  key=lambda x: x["opportunity_score"], reverse=True),
        "defend":      sorted(defend,      key=lambda x: x["opportunity_score"], reverse=True),
        "target_gaps": sorted(target_gaps, key=lambda x: x["opportunity_score"], reverse=True),
        "drop":        drop,
    }


def _get_sentiment_recommendations(app_id: int, use_llm: bool = True) -> dict:
    """
    Build sentiment-based recommendations from review data.

    Reads pre-computed sentiment labels from the database.
    Calls LLM for theme analysis (complaints, praise) only when use_llm=True.

    Args:
        app_id:  iTunes app ID.
        use_llm: Whether to run LLM theme extraction on top reviews.

    Returns:
        Dict with sentiment summary, priority fix, top complaints, and top praise.
    """
    reviews = database.get_reviews(app_id)
    if not reviews:
        return {"error": "No reviews found"}

    summary      = sentiment.get_sentiment_summary(app_id) or {}
    llm_analysis = None

    if use_llm:
        llm_analysis = llm_analyst.analyse_reviews(
            reviews[:config.LLM_TOP_REVIEWS], use_llm=True
        )

    negative_pct     = summary.get("negative_pct", 0)
    overall          = "positive" if summary.get("positive_pct", 0) > 60 else "mixed"

    return {
        "overall_sentiment": overall,
        "positive_pct":      summary.get("positive_pct", 0),
        "negative_pct":      negative_pct,
        "avg_rating":        summary.get("avg_rating", 0),
        "priority_fix":      (llm_analysis or {}).get("priority_fix"),
        "top_complaints":    (llm_analysis or {}).get("top_complaints", []),
        "top_praise":        (llm_analysis or {}).get("top_praise", []),
        "sentiment_summary": (llm_analysis or {}).get("sentiment_summary"),
    }


def _get_competitor_recommendations(app_id: int, use_llm: bool = True) -> dict:
    """
    Compare target app against top tier1 competitor and surface description gaps.

    Args:
        app_id:  iTunes app ID of the target app.
        use_llm: Whether to call the LLM for metadata comparison.

    Returns:
        Dict with competitor analysis, missing keywords, and recommendation.
    """
    target_app  = database.get_app(app_id)
    competitors = database.get_competitor_apps()
    tier1       = [c for c in competitors if c.get("competitor_tier") == "tier1"]

    if not tier1:
        logger.warning("No tier1 competitors found — skipping competitor recommendations")
        return {"error": "No tier1 competitors available"}

    top_competitor = max(tier1, key=lambda c: c.get("competitor_score") or 0.0)
    comparison     = llm_analyst.compare_competitor_metadata(
        target_app, top_competitor, use_llm=use_llm
    )

    return {
        "top_competitor":        top_competitor["name"],
        "competitor_score":      top_competitor.get("competitor_score"),
        "competitor_advantages": (comparison or {}).get("competitor_advantages", []),
        "our_advantages":        (comparison or {}).get("target_advantages", []),
        "missing_keywords":      (comparison or {}).get("missing_keywords", []),
        "recommendation":        (comparison or {}).get("recommendation"),
    }


def _suggest_description(app_id: int, use_llm: bool = True) -> str | None:
    """
    Generate a rewritten App Store description using top opportunity and gap keywords.

    Args:
        app_id:  iTunes app ID.
        use_llm: Whether to call the LLM for the rewrite.

    Returns:
        Rewritten description string, or None if use_llm=False or on failure.
    """
    target_app = database.get_app(app_id)
    if not target_app or not target_app.get("description"):
        return None

    keywords     = database.get_keywords(app_id)
    top_keywords = sorted(
        [k for k in keywords if not k.get("is_gap_keyword")],
        key=_best_score,
        reverse=True,
    )[:10]
    gap_keywords = sorted(
        [k for k in keywords if k.get("is_gap_keyword")],
        key=_best_score,
        reverse=True,
    )[:5]

    return llm_analyst.suggest_description_rewrite(
        current_description=target_app["description"],
        target_keywords=[k["keyword"] for k in top_keywords],
        gaps=[k["keyword"] for k in gap_keywords],
        use_llm=use_llm,
    )


def _build_priority_actions(
    keyword_rec: dict,
    sentiment_rec: dict,
    competitor_rec: dict,
) -> list[dict]:
    """
    Synthesise all recommendation outputs into a ranked top-3 priority action list.

    Args:
        keyword_rec:    Output of _get_keyword_recommendations().
        sentiment_rec:  Output of _get_sentiment_recommendations().
        competitor_rec: Output of _get_competitor_recommendations().

    Returns:
        List of up to 3 priority action dicts sorted high → medium → low.
    """
    actions = []

    # Best unranked high-opportunity keyword
    if keyword_rec.get("prioritise"):
        top_kw = keyword_rec["prioritise"][0]
        actions.append({
            "priority": "high",
            "area":     "keywords",
            "action":   (
                f"Target '{top_kw['keyword']}' — opportunity score "
                f"{top_kw['opportunity_score']:.2f}, currently unranked"
            ),
        })

    # Highest priority sentiment fix
    priority_fix = sentiment_rec.get("priority_fix")
    if priority_fix:
        actions.append({
            "priority": "high" if sentiment_rec.get("negative_pct", 0) > 40 else "medium",
            "area":     "sentiment",
            "action":   priority_fix,
        })

    # Best gap keyword
    if keyword_rec.get("target_gaps"):
        top_gap = keyword_rec["target_gaps"][0]
        actions.append({
            "priority": "medium",
            "area":     "keywords",
            "action":   (
                f"Target gap keyword '{top_gap['keyword']}' — "
                f"competitor '{top_gap.get('gap_competitor')}' ranks for this, we do not"
            ),
        })

    # Competitor description recommendation
    rec = competitor_rec.get("recommendation")
    if rec and len(actions) < 3:
        actions.append({
            "priority": "medium",
            "area":     "description",
            "action":   rec,
        })

    priority_order = {"high": 0, "medium": 1, "low": 2}
    return sorted(actions, key=lambda x: priority_order.get(x["priority"], 3))[:3]
