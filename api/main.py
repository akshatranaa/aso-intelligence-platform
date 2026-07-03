"""FastAPI server — exposes all ASO data and analysis as HTTP endpoints."""

from __future__ import annotations

import logging
import os
import uuid
from datetime import date, datetime
from typing import Optional

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware

import config
import database
from analysis import keyword_analysis, rank_tracker, recommendations, sentiment
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


def _run_collection(job_id: str, app_name: str, use_llm: bool) -> None:
    """
    Run the full collection pipeline and record its outcome in _jobs.

    Args:
        job_id:   Unique ID for this job, used as the _jobs dict key.
        app_name: App name to search for on the App Store.
        use_llm:  Whether to use LLM during analysis steps.
    """
    try:
        database.create_tables()

        app_data = scraper.fetch_app_metadata(app_name)
        if not app_data:
            _jobs[job_id] = {"status": "error", "detail": f"'{app_name}' not found on the App Store"}
            return

        app_data["is_target_app"] = 1
        database.save_app(app_data)
        app_id = app_data["app_id"]
        seed_keywords = keyword_analysis.derive_seed_keywords(app_data, use_llm=use_llm)
        logger.info(f"Collecting data for {app_data['name']} ({app_id})")

        competitor.discover_competitors(app_id, seed_keywords, max_depth=1)

        today = str(date.today())
        for keyword in seed_keywords:
            rank = scraper.fetch_keyword_ranking(keyword, app_id)
            if rank:
                database.save_ranking(app_id, keyword, rank, today)

        reviews = scraper.fetch_reviews(app_id)
        collected_at = datetime.now().isoformat()
        for review in reviews:
            review["app_id"]       = app_id
            review["collected_at"] = collected_at
        review_count = database.save_reviews(reviews)

        sentiment_summary = sentiment.score_all_reviews(app_id, use_llm=use_llm)
        kw_result         = keyword_analysis.run_keyword_analysis(app_id, use_llm=use_llm)
        rank_tracker.take_snapshot(app_id, seed_keywords)
        rank_tracker.compute_all_velocities(app_id)

        logger.info(f"Collection complete for {app_data['name']}")
        _jobs[job_id] = {
            "status": "done",
            "result": {
                "app_id":         app_id,
                "app_name":       app_data["name"],
                "reviews_saved":  review_count,
                "keywords_found": len(kw_result.get("top_keywords", [])),
                "gaps_found":     len(kw_result.get("gaps", [])),
                "sentiment":      sentiment_summary,
                "collected_at":   collected_at,
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


@app.get("/app/{app_id}/keywords")
def get_keywords(app_id: int, k: int = config.TOP_K_KEYWORDS) -> dict:
    """
    Fetch top keywords by opportunity score for an app.

    Args:
        app_id: iTunes numeric app ID.
        k:      Number of top keywords to return (query param, default 20).

    Returns:
        Dict with top_keywords and gap_keywords lists.
    """
    if not database.get_app(app_id):
        raise HTTPException(status_code=404, detail=f"App {app_id} not found")
    top_keywords = keyword_analysis.get_top_k_keywords(app_id, k=k)
    gap_keywords = [
        kw for kw in database.get_keywords(app_id)
        if kw.get("is_gap_keyword")
    ]
    return {
        "app_id":       app_id,
        "top_keywords": top_keywords,
        "gap_keywords": gap_keywords,
    }


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
def collect_app(app_name: str, background_tasks: BackgroundTasks, use_llm: bool = False) -> dict:
    """
    Start the full collection and analysis pipeline for an app in the background.

    Returns immediately with a job_id — the pipeline takes several minutes
    (strict rate limiting on every Apple API call), which exceeds most
    reverse-proxy request timeouts. Poll GET /collect/status/{job_id} for
    progress and the final result.

    Args:
        app_name: App name to search for on the App Store.
        use_llm:  Whether to use LLM during analysis steps (query param).

    Returns:
        Dict with job_id and initial status.
    """
    job_id = str(uuid.uuid4())
    _jobs[job_id] = {"status": "running"}
    background_tasks.add_task(_run_collection, job_id, app_name, use_llm)
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
