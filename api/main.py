"""FastAPI server — exposes all ASO data and analysis as HTTP endpoints."""

from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime
from typing import Optional

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware

import config
import database
from analysis import rank_tracker, recommendations, seeds, sentiment
from collection import competitor, scraper

logging.basicConfig(level=config.LOG_LEVEL, format=config.LOG_FORMAT)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="ASO Intelligence Platform",
    description="App Store Optimization data and analysis API",
    version="1.0.0",
)

_ALLOWED_ORIGINS = os.environ.get("ASO_ALLOWED_ORIGINS", "*").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)

_API_KEY = os.environ.get("ASO_API_KEY")


def verify_api_key(x_api_key: Optional[str] = Header(default=None)) -> None:
    """
    Reject the request if ASO_API_KEY is set and the header doesn't match.

    Args:
        x_api_key: Value of the X-API-Key request header.
    """
    if _API_KEY and x_api_key != _API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")

# In-memory job store for the async /collect flow. Render's proxy kills any
# single HTTP request after ~100s, but /collect legitimately takes several
# minutes (strict 1 req/sec rate limiting on every Apple API call), so it
# runs as a background task and the client polls for status instead.
_jobs: dict[str, dict] = {}


def _run_collection(
    job_id: str, app_name: str, use_llm: bool, country: str = config.DEFAULT_COUNTRY
) -> None:
    """
    Run the full collection pipeline and record its outcome in _jobs.

    Args:
        job_id:   Unique ID for this job, used as the _jobs dict key.
        app_name: App name to search for on the App Store.
        use_llm:  Whether to use LLM during analysis steps.
        country:  App Store country code to collect for.
    """
    try:
        database.create_tables()

        app_data = scraper.fetch_app_metadata(app_name, country)
        if not app_data:
            _jobs[job_id] = {
                "status": "error",
                "detail": f"'{app_name}' not found on the {country.upper()} App Store",
            }
            return

        app_data["is_target_app"] = 1
        database.save_app(app_data)
        app_id = app_data["app_id"]
        # Derive seeds once and reuse everywhere (one LLM call, consistent status).
        seed_keywords, used_llm_seeds = seeds.derive_seed_keywords(
            app_data, use_llm=use_llm
        )
        logger.info(f"Collecting data for {app_data['name']} ({app_id}) [{country}]")

        competitor.discover_competitors(app_id, seed_keywords, use_llm=use_llm, country=country)

        reviews = scraper.fetch_reviews(app_id, country)
        collected_at = datetime.now().isoformat()
        for review in reviews:
            review["app_id"]       = app_id
            review["collected_at"] = collected_at
        review_count = database.save_reviews(reviews)

        sentiment_summary = sentiment.score_all_reviews(app_id, use_llm=use_llm)

        # Rank-track the seed keywords plus any keyword already tracked for this
        # app (custom-added keywords keep refreshing so velocity can accumulate).
        tracked = list(dict.fromkeys(
            list(seed_keywords)
            + [row["keyword"] for row in database.get_all_rankings(app_id)]
        ))
        rank_tracker.take_snapshot(app_id, tracked, country)
        rank_tracker.compute_all_velocities(app_id)

        seed_warning = (
            "LLM seed generation was unavailable (model busy) — used generic "
            "category seeds instead, so competitor results may be less relevant."
            if (use_llm and not used_llm_seeds) else None
        )

        logger.info(f"Collection complete for {app_data['name']}")
        _jobs[job_id] = {
            "status": "done",
            "result": {
                "app_id":           app_id,
                "app_name":         app_data["name"],
                "country":          country,
                "reviews_saved":    review_count,
                "keywords_tracked": len(tracked),
                "sentiment":        sentiment_summary,
                "seed_warning":     seed_warning,
                "collected_at":     collected_at,
            },
        }
    except Exception as e:
        logger.error(f"Collection job {job_id} failed: {e}")
        _jobs[job_id] = {"status": "error", "detail": str(e)}


@app.get("/")
def health_check() -> dict:
    """
    Confirm the server is running.

    Returns:
        Dict with status and current timestamp.
    """
    return {"status": "ok", "timestamp": datetime.now().isoformat()}


@app.get("/app/{app_id}")
def get_app(app_id: int) -> dict:
    """
    Fetch metadata for one app.

    Args:
        app_id: iTunes numeric app ID.

    Returns:
        App metadata dict.
    """
    app_data = database.get_app(app_id)
    if not app_data:
        raise HTTPException(status_code=404, detail=f"App {app_id} not found")
    return app_data


@app.get("/app/{app_id}/reviews")
def get_reviews(app_id: int) -> dict:
    """
    Fetch all stored reviews for an app.

    Args:
        app_id: iTunes numeric app ID.

    Returns:
        Dict with total count and list of review dicts.
    """
    if not database.get_app(app_id):
        raise HTTPException(status_code=404, detail=f"App {app_id} not found")
    reviews = database.get_reviews(app_id)
    return {"app_id": app_id, "total": len(reviews), "reviews": reviews}


@app.get("/app/{app_id}/sentiment")
def get_sentiment(app_id: int) -> dict:
    """
    Fetch pre-computed sentiment summary for an app.

    Does not recompute — reads already-scored reviews from database.

    Args:
        app_id: iTunes numeric app ID.

    Returns:
        Sentiment summary with counts, percentages, and average rating.
    """
    if not database.get_app(app_id):
        raise HTTPException(status_code=404, detail=f"App {app_id} not found")
    summary = sentiment.get_sentiment_summary(app_id)
    if not summary:
        raise HTTPException(
            status_code=404,
            detail="No sentiment data found — run /collect first",
        )
    return summary


@app.get("/app/{app_id}/rankings")
def get_rankings(app_id: int) -> dict:
    """
    Fetch ranking summary with trends for all tracked keywords.

    Args:
        app_id: iTunes numeric app ID.

    Returns:
        Dict with ranking summary list including trend labels.
    """
    if not database.get_app(app_id):
        raise HTTPException(status_code=404, detail=f"App {app_id} not found")
    summary = rank_tracker.get_ranking_summary(app_id)
    return {"app_id": app_id, "total": len(summary), "rankings": summary}


@app.post("/app/{app_id}/rankings/track", dependencies=[Depends(verify_api_key)])
def track_keyword(app_id: int, keyword: str) -> dict:
    """
    Start rank-tracking a custom keyword for an app (one live snapshot).

    Args:
        app_id:  iTunes numeric app ID.
        keyword: Keyword to begin tracking (query param).

    Returns:
        The refreshed ranking summary including the new keyword.
    """
    app_data = database.get_app(app_id)
    if not app_data:
        raise HTTPException(status_code=404, detail=f"App {app_id} not found")
    keyword = keyword.strip()
    if not keyword:
        raise HTTPException(status_code=400, detail="keyword must not be empty")
    country = app_data.get("country") or config.DEFAULT_COUNTRY
    summary = rank_tracker.track_keyword(app_id, keyword, country=country)
    return {"app_id": app_id, "total": len(summary), "rankings": summary}


@app.post("/app/{app_id}/rankings/refresh", dependencies=[Depends(verify_api_key)])
def refresh_rankings(app_id: int) -> dict:
    """
    Re-snapshot every tracked keyword for an app without a full collection.

    Rankings-only (no metadata/competitor/review/sentiment work), so it runs
    synchronously and returns the updated summary.

    Args:
        app_id: iTunes numeric app ID.

    Returns:
        The refreshed ranking summary after re-snapshotting and recomputing velocity.
    """
    app_data = database.get_app(app_id)
    if not app_data:
        raise HTTPException(status_code=404, detail=f"App {app_id} not found")
    country = app_data.get("country") or config.DEFAULT_COUNTRY
    summary = rank_tracker.refresh_rankings(app_id, country=country)
    return {"app_id": app_id, "total": len(summary), "rankings": summary}


@app.get("/app/{app_id}/rankings/compare")
def compare_competitor_ranks(app_id: int, keyword: str) -> dict:
    """
    Compare where the target and its top competitors rank for one keyword.

    Live iTunes lookups (one per app), so this is bounded and on-demand.

    Args:
        app_id:  iTunes numeric app ID of the target app.
        keyword: Keyword to compare ranks for (query param).

    Returns:
        Dict with the keyword, the target's rank, and each competitor's rank.
    """
    app_data = database.get_app(app_id)
    if not app_data:
        raise HTTPException(status_code=404, detail=f"App {app_id} not found")
    keyword = keyword.strip()
    if not keyword:
        raise HTTPException(status_code=400, detail="keyword must not be empty")
    country = app_data.get("country") or config.DEFAULT_COUNTRY
    return rank_tracker.compare_competitor_ranks(app_id, keyword, country=country)


@app.get("/app/{app_id}/competitors")
def get_competitors(app_id: int) -> dict:
    """
    Fetch all discovered competitor apps split by tier.

    Args:
        app_id: iTunes numeric app ID.

    Returns:
        Dict with tier1 and tier2 competitor lists.
    """
    if not database.get_app(app_id):
        raise HTTPException(status_code=404, detail=f"App {app_id} not found")
    all_competitors = database.get_competitors(app_id)
    tier1 = [c for c in all_competitors if c.get("competitor_tier") == "tier1"]
    tier2 = [c for c in all_competitors if c.get("competitor_tier") == "tier2"]
    return {
        "app_id": app_id,
        "total":  len(all_competitors),
        "tier1":  tier1,
        "tier2":  tier2,
    }


@app.get("/app/{app_id}/recommendations")
def get_recommendations(app_id: int, use_llm: bool = False) -> dict:
    """
    Generate a full recommendation report for an app.

    Args:
        app_id:  iTunes numeric app ID.
        use_llm: Whether to call LLM for competitor comparison and description
                 rewrite (query param, default False to avoid unexpected costs).

    Returns:
        Full recommendation report with priority actions.
    """
    if not database.get_app(app_id):
        raise HTTPException(status_code=404, detail=f"App {app_id} not found")
    return recommendations.generate_recommendations(app_id, use_llm=use_llm)


@app.post("/collect/{app_name}", dependencies=[Depends(verify_api_key)])
def collect_app(
    app_name: str,
    background_tasks: BackgroundTasks,
    use_llm: bool = False,
    country: str = config.DEFAULT_COUNTRY,
) -> dict:
    """
    Start the full collection and analysis pipeline for an app in the background.

    Returns immediately with a job_id — the pipeline takes several minutes
    (strict rate limiting on every Apple API call), which exceeds most
    reverse-proxy request timeouts. Poll GET /collect/status/{job_id} for
    progress and the final result.

    Args:
        app_name: App name to search for on the App Store.
        use_llm:  Whether to use LLM during analysis steps (query param).
        country:  App Store country code to collect for (query param).

    Returns:
        Dict with job_id and initial status.
    """
    job_id = str(uuid.uuid4())
    _jobs[job_id] = {"status": "running"}
    background_tasks.add_task(_run_collection, job_id, app_name, use_llm, country)
    return {"job_id": job_id, "status": "running"}


@app.get("/collect/status/{job_id}")
def get_collect_status(job_id: str) -> dict:
    """
    Poll the status of a background collection job.

    Args:
        job_id: ID returned by POST /collect/{app_name}.

    Returns:
        Dict with status ("running", "done", or "error") and, once
        finished, either a result dict or an error detail string.
    """
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    return {"job_id": job_id, **job}
