"""FastAPI server — exposes all ASO data and analysis as HTTP endpoints."""

from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime
from typing import Optional

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

import config
import database
from analysis import rank_tracker, recommendations, seeds, sentiment
from api.auth import get_current_user, require_app_membership
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


@app.on_event("startup")
def _startup() -> None:
    """Ensure the schema (incl. the multi-country migration) is current on boot."""
    try:
        database.create_tables()
    except Exception as e:
        logger.error(f"Startup schema init failed: {e}")


def _set_progress(job_id: str, step: str, index: int, total: int = 5) -> None:
    """
    Update a running job's progress step, preserving its other fields.

    Args:
        job_id: _jobs key.
        step:   Human-readable description of the stage now running.
        index:  1-based position of this stage (for a progress indicator).
        total:  Total number of stages.
    """
    if job_id in _jobs:
        _jobs[job_id] = {
            **_jobs[job_id],
            "step": step,
            "step_index": index,
            "step_total": total,
        }


def _run_collection(
    job_id: str,
    app_name: str,
    use_llm: bool,
    country: str = config.DEFAULT_COUNTRY,
    force: bool = False,
    user_id: str | None = None,
    app_id: int | None = None,
) -> None:
    """
    Run the full collection pipeline and record its outcome in _jobs.

    Args:
        job_id:   Unique ID for this job, used as the _jobs dict key.
        app_name: App name to search for on the App Store.
        use_llm:  Whether to use LLM during analysis steps.
        country:  App Store country code to collect for.
        force:    Re-discover competitors even if a recent result exists (also
                  forces seed regeneration).
        user_id:  Supabase user the collected app is assigned to (ownership).
        app_id:   Exact iTunes ID to collect (from autocomplete). When given,
                  the app is looked up by ID rather than searched by name, so
                  the picked app is collected exactly instead of the top search hit.
    """
    try:
        database.create_tables()
        _set_progress(job_id, "Looking up app metadata…", 1)

        # Prefer an exact lookup by the picked ID; fall back to a name search.
        if app_id is not None:
            app_data = scraper.fetch_app_by_id(app_id, country)
        else:
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
        # Assign the app to the collecting user so it shows in their list.
        if user_id:
            database.add_user_app(user_id, app_id)
        logger.info(f"Collecting data for {app_data['name']} ({app_id}) [{country}]")

        # Fast path: if this app+country was already collected recently (competitors
        # still fresh AND it already has tracked keywords), skip seed generation and
        # competitor discovery — just refresh reviews/rankings against the existing set.
        existing_tracked = [
            row["keyword"] for row in database.get_all_rankings(app_id, country)
        ]
        reuse = (
            not force
            and bool(existing_tracked)
            and competitor.has_fresh_competitors(app_id, country)
        )

        if reuse:
            seed_keywords, used_llm_seeds = [], True
            _set_progress(job_id, "Reusing cached competitors…", 2)
            logger.info(
                f"Re-collect fast path for {app_id} [{country}]: reusing seeds + "
                f"competitors, refreshing reviews/rankings only"
            )
        else:
            _set_progress(job_id, "Deriving keyword seeds…", 2)
            # Derive seeds once and reuse everywhere (one LLM call, consistent status).
            seed_keywords, used_llm_seeds = seeds.derive_seed_keywords(
                app_data, use_llm=use_llm
            )
            # Persist the seeds used, so they're editable on the Competitors page.
            database.set_seed_keywords(app_id, country, seed_keywords)
            _set_progress(job_id, "Discovering & scoring competitors…", 2)

        competitor.discover_competitors(
            app_id, seed_keywords, use_llm=use_llm, country=country, force=force
        )

        _set_progress(job_id, "Fetching recent reviews…", 3)
        reviews = scraper.fetch_reviews(app_id, country)
        collected_at = datetime.now().isoformat()
        for review in reviews:
            review["app_id"]       = app_id
            review["country"]      = country
            review["collected_at"] = collected_at
        review_count = database.save_reviews(reviews)

        _set_progress(job_id, "Scoring review sentiment…", 4)
        sentiment_summary = sentiment.score_all_reviews(
            app_id, use_llm=use_llm, country=country
        )

        _set_progress(job_id, "Tracking keyword rankings…", 5)
        # Rank-track the seed keywords plus any keyword already tracked for this
        # app+country (custom-added keywords keep refreshing so velocity accrues).
        tracked = list(dict.fromkeys(list(seed_keywords) + existing_tracked))
        rank_tracker.take_snapshot(app_id, tracked, country)
        rank_tracker.compute_all_velocities(app_id, country)

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


def _run_rediscovery(
    job_id: str, app_id: int, keywords: list[str], use_llm: bool, country: str
) -> None:
    """
    Apply an edited seed-keyword set incrementally (background task).

    Diffs the new seeds against the stored ones: a removed keyword drops only the
    competitors no surviving keyword still surfaces (no API/LLM), and an added
    keyword searches + judges that keyword's candidates only. The first edit on an
    app collected before the seed→competitor map existed does one full rebuild.

    Args:
        job_id:   _jobs key.
        app_id:   Target app.
        keywords: The edited seed keyword list.
        use_llm:  Whether to use the LLM relevance judge.
        country:  App Store country.
    """
    try:
        database.create_tables()
        app_data = database.get_app(app_id)
        if not app_data:
            _jobs[job_id] = {"status": "error", "detail": f"App {app_id} not found"}
            return
        total = competitor.apply_seed_edit(
            app_id, keywords, country=country, use_llm=use_llm
        )
        logger.info(f"Rediscovery complete for {app_id} [{country}]: {total}")
        _jobs[job_id] = {
            "status": "done",
            "result": {"app_id": app_id, "country": country, "total": total},
        }
    except Exception as e:
        logger.error(f"Rediscovery job {job_id} failed: {e}")
        _jobs[job_id] = {"status": "error", "detail": str(e)}


@app.get("/")
def health_check() -> dict:
    """
    Confirm the server is running.

    Returns:
        Dict with status and current timestamp.
    """
    return {"status": "ok", "timestamp": datetime.now().isoformat()}


@app.get("/apps")
def list_apps(user: dict = Depends(get_current_user)) -> dict:
    """
    List the collected target apps owned by the authenticated user.

    Returns:
        Dict with a list of {app_id, name, category, countries} entries,
        sorted by name.
    """
    targets = database.get_user_apps(user["id"])
    apps = [
        {
            "app_id":    a["app_id"],
            "name":      a["name"],
            "category":  a.get("category"),
            "countries": database.get_app_countries(a["app_id"]),
        }
        for a in sorted(targets, key=lambda a: (a.get("name") or "").lower())
    ]
    return {"total": len(apps), "apps": apps}


@app.get("/search")
def search_apps(
    term: str,
    country: str = config.DEFAULT_COUNTRY,
    limit: int = 8,
    user: dict = Depends(get_current_user),
) -> dict:
    """
    App Store search suggestions for the collect-form autocomplete.

    Args:
        term:    Partial or full app name (query param).
        country: App Store country code (query param).
        limit:   Max suggestions (query param).

    Returns:
        Dict with a list of {app_id, name, category, seller, artwork} suggestions.
    """
    term = term.strip()
    if len(term) < 2:
        return {"results": []}
    results = scraper.search_apps(term, country, max(1, min(limit, 15)))
    return {"results": results}


@app.get("/app/{app_id}", dependencies=[Depends(require_app_membership)])
def get_app(app_id: int, country: Optional[str] = None) -> dict:
    """
    Fetch metadata for one app, optionally with per-country metrics.

    Args:
        app_id:  iTunes numeric app ID.
        country: If given, overlay that country's rating count / rating / version
                 / description from the per-country snapshot.

    Returns:
        App metadata dict, plus a `countries` list of stores it has data for.
    """
    app_data = database.get_app(app_id)
    if not app_data:
        raise HTTPException(status_code=404, detail=f"App {app_id} not found")
    if country:
        stats = database.get_app_country_stats(app_id, country)
        if stats:
            for k in ("rating_count", "avg_rating", "price", "version",
                      "description", "collected_at"):
                if stats.get(k) is not None:
                    app_data[k] = stats[k]
            app_data["country"] = country
    app_data["countries"] = database.get_app_countries(app_id)
    return app_data


@app.get("/app/{app_id}/countries", dependencies=[Depends(require_app_membership)])
def get_app_countries(app_id: int) -> dict:
    """
    List the App Store countries an app has been collected for.

    Args:
        app_id: iTunes numeric app ID.

    Returns:
        Dict with a sorted list of two-letter country codes.
    """
    if not database.get_app(app_id):
        raise HTTPException(status_code=404, detail=f"App {app_id} not found")
    return {"app_id": app_id, "countries": database.get_app_countries(app_id)}


@app.post("/app/{app_id}/untrack", dependencies=[Depends(verify_api_key)])
def untrack_app(app_id: int, user: dict = Depends(require_app_membership)) -> dict:
    """
    Remove an app from the user's list without deleting its collected data.

    Only drops this user's ownership — other users who collected the same app
    keep it, and the app's collected data is preserved.

    Args:
        app_id: iTunes numeric app ID.
        user:   The authenticated owner (injected).

    Returns:
        Dict confirming the app is untracked for this user.
    """
    database.remove_user_app(user["id"], app_id)
    return {"app_id": app_id, "untracked": True}


@app.get("/app/{app_id}/reviews", dependencies=[Depends(require_app_membership)])
def get_reviews(app_id: int, country: Optional[str] = None) -> dict:
    """
    Fetch stored reviews for an app, optionally scoped to one country.

    Args:
        app_id:  iTunes numeric app ID.
        country: If given, only reviews for that App Store country.

    Returns:
        Dict with total count and list of review dicts.
    """
    if not database.get_app(app_id):
        raise HTTPException(status_code=404, detail=f"App {app_id} not found")
    reviews = database.get_reviews(app_id, country)
    return {"app_id": app_id, "total": len(reviews), "reviews": reviews}


@app.get("/app/{app_id}/sentiment", dependencies=[Depends(require_app_membership)])
def get_sentiment(app_id: int, country: Optional[str] = None) -> dict:
    """
    Fetch pre-computed sentiment summary for an app, optionally per country.

    Does not recompute — reads already-scored reviews from database.

    Args:
        app_id:  iTunes numeric app ID.
        country: If given, only reviews for that App Store country.

    Returns:
        Sentiment summary with counts, percentages, and average rating.
    """
    if not database.get_app(app_id):
        raise HTTPException(status_code=404, detail=f"App {app_id} not found")
    summary = sentiment.get_sentiment_summary(app_id, country)
    if not summary:
        raise HTTPException(
            status_code=404,
            detail="No sentiment data found — run /collect first",
        )
    return summary


@app.get("/app/{app_id}/rankings", dependencies=[Depends(require_app_membership)])
def get_rankings(app_id: int, country: Optional[str] = None) -> dict:
    """
    Fetch ranking summary with trends for all tracked keywords.

    Args:
        app_id:  iTunes numeric app ID.
        country: If given, only keywords tracked for that App Store country.

    Returns:
        Dict with ranking summary list including trend labels.
    """
    if not database.get_app(app_id):
        raise HTTPException(status_code=404, detail=f"App {app_id} not found")
    summary = rank_tracker.get_ranking_summary(app_id, country)
    return {"app_id": app_id, "total": len(summary), "rankings": summary}


def _resolve_country(app_data: dict, country: Optional[str]) -> str:
    """Pick the explicit country if given, else the app's collected country."""
    return country or app_data.get("country") or config.DEFAULT_COUNTRY


@app.post(
    "/app/{app_id}/rankings/track",
    dependencies=[Depends(verify_api_key), Depends(require_app_membership)],
)
def track_keyword(app_id: int, keyword: str, country: Optional[str] = None) -> dict:
    """
    Start rank-tracking a custom keyword for an app (one live snapshot).

    Args:
        app_id:  iTunes numeric app ID.
        keyword: Keyword to begin tracking (query param).
        country: App Store country to track in (query param); defaults to the
                 app's collected country.

    Returns:
        The refreshed ranking summary including the new keyword.
    """
    app_data = database.get_app(app_id)
    if not app_data:
        raise HTTPException(status_code=404, detail=f"App {app_id} not found")
    keyword = keyword.strip()
    if not keyword:
        raise HTTPException(status_code=400, detail="keyword must not be empty")
    summary = rank_tracker.track_keyword(
        app_id, keyword, country=_resolve_country(app_data, country)
    )
    return {"app_id": app_id, "total": len(summary), "rankings": summary}


@app.post(
    "/app/{app_id}/rankings/refresh",
    dependencies=[Depends(verify_api_key), Depends(require_app_membership)],
)
def refresh_rankings(app_id: int, country: Optional[str] = None) -> dict:
    """
    Re-snapshot every tracked keyword for an app without a full collection.

    Rankings-only (no metadata/competitor/review/sentiment work), so it runs
    synchronously and returns the updated summary.

    Args:
        app_id:  iTunes numeric app ID.
        country: App Store country to refresh (query param); defaults to the
                 app's collected country.

    Returns:
        The refreshed ranking summary after re-snapshotting and recomputing velocity.
    """
    app_data = database.get_app(app_id)
    if not app_data:
        raise HTTPException(status_code=404, detail=f"App {app_id} not found")
    summary = rank_tracker.refresh_rankings(
        app_id, country=_resolve_country(app_data, country)
    )
    return {"app_id": app_id, "total": len(summary), "rankings": summary}


@app.delete(
    "/app/{app_id}/rankings/keyword",
    dependencies=[Depends(verify_api_key), Depends(require_app_membership)],
)
def remove_keyword(app_id: int, keyword: str, country: Optional[str] = None) -> dict:
    """
    Stop tracking a keyword — delete its ranking rows for the app+country.

    Args:
        app_id:  iTunes numeric app ID.
        keyword: Keyword to remove (query param).
        country: App Store country (query param); defaults to the app's country.

    Returns:
        The ranking summary after removal.
    """
    app_data = database.get_app(app_id)
    if not app_data:
        raise HTTPException(status_code=404, detail=f"App {app_id} not found")
    resolved = _resolve_country(app_data, country)
    database.delete_ranking_keyword(app_id, keyword.strip(), resolved)
    summary = rank_tracker.get_ranking_summary(app_id, resolved)
    return {"app_id": app_id, "total": len(summary), "rankings": summary}


@app.get("/app/{app_id}/rankings/compare", dependencies=[Depends(require_app_membership)])
def compare_competitor_ranks(
    app_id: int,
    keyword: str,
    n: int = config.RANK_COMPETITOR_COMPARE_MAX,
    country: Optional[str] = None,
) -> dict:
    """
    Compare where the target and its top-N competitors rank for one keyword.

    Live iTunes lookups (one per app), so this is bounded and on-demand. n is
    clamped to 1–25 to keep the total number of rate-limited calls reasonable.

    Args:
        app_id:  iTunes numeric app ID of the target app.
        keyword: Keyword to compare ranks for (query param).
        n:       Number of top competitors (by score) to compare (query param).
        country: App Store country to check ranks in (query param). Defaults to
                 the country the app was collected for; pass any code to compare
                 that keyword in a different store independently.

    Returns:
        Dict with the keyword, the target's rank, and each competitor's rank.
    """
    app_data = database.get_app(app_id)
    if not app_data:
        raise HTTPException(status_code=404, detail=f"App {app_id} not found")
    keyword = keyword.strip()
    if not keyword:
        raise HTTPException(status_code=400, detail="keyword must not be empty")
    n = max(1, min(n, 25))
    resolved_country = country or app_data.get("country") or config.DEFAULT_COUNTRY
    return rank_tracker.compare_competitor_ranks(
        app_id, keyword, max_competitors=n, country=resolved_country
    )


@app.get("/app/{app_id}/competitors", dependencies=[Depends(require_app_membership)])
def get_competitors(app_id: int, country: Optional[str] = None) -> dict:
    """
    Fetch all discovered competitor apps split by tier.

    Args:
        app_id:  iTunes numeric app ID.
        country: If given, only competitors discovered for that country.

    Returns:
        Dict with tier1 and tier2 competitor lists.
    """
    if not database.get_app(app_id):
        raise HTTPException(status_code=404, detail=f"App {app_id} not found")
    all_competitors = database.get_competitors(app_id, country)
    tier1 = [c for c in all_competitors if c.get("competitor_tier") == "tier1"]
    tier2 = [c for c in all_competitors if c.get("competitor_tier") == "tier2"]
    return {
        "app_id": app_id,
        "total":  len(all_competitors),
        "tier1":  tier1,
        "tier2":  tier2,
    }


@app.delete(
    "/app/{app_id}/competitors/{competitor_app_id}",
    dependencies=[Depends(verify_api_key), Depends(require_app_membership)],
)
def remove_competitor(
    app_id: int, competitor_app_id: int, country: Optional[str] = None
) -> dict:
    """
    Remove a competitor from an app's list (and purge it if it's orphaned junk).

    Args:
        app_id:            iTunes numeric app ID of the target.
        competitor_app_id: The competitor to remove.
        country:           App Store country (query param); defaults to the app's.

    Returns:
        Dict with the removed id and whether its app row was fully purged.
    """
    app_data = database.get_app(app_id)
    if not app_data:
        raise HTTPException(status_code=404, detail=f"App {app_id} not found")
    resolved = _resolve_country(app_data, country)
    purged = database.delete_competitor(app_id, competitor_app_id, resolved)
    return {"app_id": app_id, "removed": competitor_app_id, "purged": purged}


@app.get("/app/{app_id}/seeds", dependencies=[Depends(require_app_membership)])
def get_seeds(app_id: int, country: Optional[str] = None) -> dict:
    """
    Fetch the competitor-discovery seed keywords for an app+country.

    Args:
        app_id:  iTunes numeric app ID.
        country: App Store country (query param); defaults to the app's.

    Returns:
        Dict with the seed keyword list.
    """
    app_data = database.get_app(app_id)
    if not app_data:
        raise HTTPException(status_code=404, detail=f"App {app_id} not found")
    resolved = _resolve_country(app_data, country)
    return {
        "app_id": app_id,
        "country": resolved,
        "seeds": database.get_seed_keywords(app_id, resolved),
    }


@app.post(
    "/app/{app_id}/competitors/rediscover",
    dependencies=[Depends(verify_api_key), Depends(require_app_membership)],
)
def rediscover_competitors(
    app_id: int,
    background_tasks: BackgroundTasks,
    kw: list[str] = Query(default=[]),
    country: Optional[str] = None,
    use_llm: bool = True,
    user: dict = Depends(get_current_user),
) -> dict:
    """
    Re-run competitor discovery for an edited seed-keyword set (background job).

    Saves the given seeds, clears the app+country competitors, and re-discovers
    from all of them. Returns a job_id — poll GET /collect/status/{job_id}.

    Args:
        app_id:  iTunes numeric app ID.
        kw:      Seed keywords (repeated query param, e.g. ?kw=vpn&kw=proxy).
        country: App Store country (query param); defaults to the app's.
        use_llm: Whether to use the LLM relevance judge (query param).

    Returns:
        Dict with job_id and initial status.
    """
    app_data = database.get_app(app_id)
    if not app_data:
        raise HTTPException(status_code=404, detail=f"App {app_id} not found")
    keywords = list(dict.fromkeys(k.strip() for k in kw if k.strip()))
    if not keywords:
        raise HTTPException(status_code=400, detail="At least one seed keyword is required")
    resolved = _resolve_country(app_data, country)
    job_id = str(uuid.uuid4())
    _jobs[job_id] = {"status": "running", "user_id": user["id"]}
    background_tasks.add_task(
        _run_rediscovery, job_id, app_id, keywords, use_llm, resolved
    )
    return {"job_id": job_id, "status": "running"}


@app.get("/app/{app_id}/recommendations", dependencies=[Depends(require_app_membership)])
def get_recommendations(
    app_id: int, use_llm: bool = False, country: Optional[str] = None
) -> dict:
    """
    Generate a full recommendation report for an app.

    Args:
        app_id:  iTunes numeric app ID.
        use_llm: Whether to call LLM for competitor comparison and description
                 rewrite (query param, default False to avoid unexpected costs).
        country: If given, scope reviews/rankings/competitors to that country.

    Returns:
        Full recommendation report with priority actions.
    """
    if not database.get_app(app_id):
        raise HTTPException(status_code=404, detail=f"App {app_id} not found")
    return recommendations.generate_recommendations(
        app_id, use_llm=use_llm, country=country
    )


@app.post("/collect/{app_name}", dependencies=[Depends(verify_api_key)])
def collect_app(
    app_name: str,
    background_tasks: BackgroundTasks,
    use_llm: bool = False,
    country: str = config.DEFAULT_COUNTRY,
    force: bool = False,
    app_id: Optional[int] = None,
    user: dict = Depends(get_current_user),
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
        force:    Re-discover competitors even if a recent result exists (query param).
        app_id:   Exact iTunes ID to collect (query param). Sent by the
                  autocomplete pick so the chosen app is collected exactly,
                  rather than the top result of a name search.

    Returns:
        Dict with job_id and initial status.
    """
    job_id = str(uuid.uuid4())
    _jobs[job_id] = {"status": "running", "user_id": user["id"]}
    background_tasks.add_task(
        _run_collection, job_id, app_name, use_llm, country, force, user["id"], app_id
    )
    return {"job_id": job_id, "status": "running"}


@app.get("/collect/status/{job_id}")
def get_collect_status(
    job_id: str, user: dict = Depends(get_current_user)
) -> dict:
    """
    Poll the status of a background collection job (owner only).

    Args:
        job_id: ID returned by POST /collect/{app_name}.
        user:   The authenticated user (must own the job).

    Returns:
        Dict with status ("running", "done", or "error") and, once
        finished, either a result dict or an error detail string.
    """
    job = _jobs.get(job_id)
    if not job or job.get("user_id") not in (None, user["id"]):
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    return {"job_id": job_id, **{k: v for k, v in job.items() if k != "user_id"}}
