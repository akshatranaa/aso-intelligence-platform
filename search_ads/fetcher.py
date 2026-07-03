"""Fetches campaign and keyword performance data from Apple Search Ads API."""

from __future__ import annotations

import logging
import os
from datetime import date, datetime, timedelta

import httpx
from dotenv import load_dotenv

import config
import database
from search_ads import auth

load_dotenv()

logger = logging.getLogger(__name__)

_ORG_ID = os.getenv("SEARCH_ADS_ORG_ID")


def _get_headers() -> dict:
    """
    Build the auth and context headers required by every Search Ads API request.

    Returns:
        Dict with Authorization and X-AP-Context headers.
    """
    return {
        "Authorization": f"Bearer {auth.get_access_token()}",
        "X-AP-Context":  f"orgId={_ORG_ID}",
        "Content-Type":  "application/json",
    }


def fetch_campaigns(app_id: int) -> list[dict]:
    """
    Fetch all Search Ads campaigns for an app and save them to the database.

    Args:
        app_id: iTunes numeric app ID to filter campaigns by.

    Returns:
        List of saved campaign dicts, or [] on failure.
    """
    url = f"{config.SEARCH_ADS_BASE_URL}/campaigns"
    try:
        response = httpx.get(url, headers=_get_headers())
        response.raise_for_status()
        all_campaigns = response.json().get("data", [])

        # Filter to only campaigns belonging to this app
        our_campaigns = [
            c for c in all_campaigns
            if c.get("adamId") == app_id
        ]

        saved = []
        for c in our_campaigns:
            campaign_dict = {
                "campaign_id":  str(c["id"]),
                "app_id":       app_id,
                "name":         c.get("name"),
                "bucket_type":  None,
                "start_date":   (c.get("startTime") or "")[:10],
                "end_date":     (c.get("endTime") or "")[:10] or None,
                "total_budget": float((c.get("budgetAmount") or {}).get("amount", 0)),
                "daily_budget": float((c.get("dailyBudgetAmount") or {}).get("amount", 0)),
                "status":       c.get("status", "ENABLED").lower(),
                "created_at":   datetime.now().isoformat(),
            }
            database.save_campaign(campaign_dict)
            saved.append(campaign_dict)

        logger.info(f"Fetched {len(saved)} campaigns for app {app_id}")
        return saved

    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP {e.response.status_code} fetching campaigns: {e.response.text}")
        return []
    except Exception as e:
        logger.error(f"Unexpected error fetching campaigns: {e}")
        return []


def fetch_keyword_report(
    campaign_id: str,
    start_date: str,
    end_date: str,
) -> list[dict]:
    """
    Fetch per-keyword performance totals for one campaign over a date range.

    Args:
        campaign_id: Search Ads campaign ID string.
        start_date:  Report start date in YYYY-MM-DD format.
        end_date:    Report end date in YYYY-MM-DD format.

    Returns:
        List of saved keyword data dicts, or [] on failure.
    """
    url = f"{config.SEARCH_ADS_BASE_URL}/reports/campaigns/{campaign_id}/keywords"
    body = {
        "startTime":   start_date,
        "endTime":     end_date,
        "granularity": "SUMMARY",
        "selector": {
            "orderBy": [{"field": "impressions", "sortOrder": "DESCENDING"}],
            "pagination": {"offset": 0, "limit": 1000},
        },
        "returnRowTotals":            True,
        "returnRecordsWithNoMetrics": False,
    }
    try:
        response = httpx.post(url, headers=_get_headers(), json=body)
        response.raise_for_status()
        rows = (
            response.json()
            .get("data", {})
            .get("reportingDataResponse", {})
            .get("row", [])
        )

        saved = []
        for row in rows:
            meta  = row.get("metadata", {})
            total = row.get("total", {})
            kw_dict = {
                "campaign_id":      campaign_id,
                "keyword":          meta.get("keyword"),
                "date":             end_date,
                "impressions":      total.get("impressions", 0),
                "taps":             total.get("taps", 0),
                "installs":         total.get("installs", 0),
                "spend":            float((total.get("localSpend") or {}).get("amount", 0)),
                "avg_cpt":          float((total.get("avgCPT") or {}).get("amount", 0)),
                "avg_cpi":          float((total.get("avgCPI") or {}).get("amount", 0)),
                "tap_through_rate": total.get("ttr", 0.0),
                "conversion_rate":  total.get("conversionRate", 0.0),
                "impression_share": total.get("impressionShare", 0.0),
                "is_search_match":  1 if meta.get("matchType") == "SEARCH_MATCH" else 0,
            }
            database.save_keyword_data(kw_dict)
            saved.append(kw_dict)

        logger.info(f"Fetched {len(saved)} keyword rows for campaign {campaign_id}")
        return saved

    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP {e.response.status_code} fetching keyword report: {e.response.text}")
        return []
    except Exception as e:
        logger.error(f"Unexpected error fetching keyword report: {e}")
        return []


def _compute_revised_opportunity(row: dict, relevance: float) -> float:
    """
    Compute a revised opportunity score using confirmed Search Ads metrics.

    Higher score = better keyword to target.

    Args:
        row:       Keyword data dict from search_ads_keyword_data.
        relevance: Proxy relevance score reused from existing keyword row.

    Returns:
        Float clamped to [0.0, 1.0].
    """
    confirmed_volume = row.get("impression_share", 0.0)
    conversion_rate  = row.get("conversion_rate", 0.0)

    avg_cpi       = row.get("avg_cpi") or config.MAX_CPI
    cpi_efficiency = 1.0 - min(avg_cpi / config.MAX_CPI, 1.0)

    # High impression share for us → low difficulty for competitors
    confirmed_difficulty = 1.0 - confirmed_volume

    w = config.REVISED_OPPORTUNITY_WEIGHTS
    score = (
        confirmed_volume     * w["confirmed_volume"]
        + conversion_rate    * w["conversion_rate"]
        + relevance          * w["relevance"]
        + cpi_efficiency     * w["cpi_efficiency"]
        - confirmed_difficulty * w["confirmed_difficulty"]
    )
    return max(0.0, min(1.0, score))


def update_keyword_scores(app_id: int) -> int:
    """
    Read Search Ads keyword data and write confirmed scores back to keywords table.

    Args:
        app_id: iTunes numeric app ID.

    Returns:
        Number of keyword rows updated.
    """
    existing_keywords = {
        kw["keyword"]: kw
        for kw in database.get_keywords(app_id)
    }

    campaigns = database.get_campaigns(app_id)
    updated = 0

    for campaign in campaigns:
        rows = database.get_keyword_data(campaign["campaign_id"])
        for row in rows:
            kw_str = row.get("keyword")
            if not kw_str or kw_str not in existing_keywords:
                continue

            relevance = existing_keywords[kw_str].get("proxy_opportunity", 0.0)
            revised   = _compute_revised_opportunity(row, relevance)

            database.update_keyword_confirmed_scores(
                app_id=app_id,
                keyword=kw_str,
                confirmed_volume=row["impression_share"],
                confirmed_conversion=row["conversion_rate"],
                confirmed_cpi=row["avg_cpi"],
                revised_opportunity=revised,
                updated_at=datetime.now().isoformat(),
            )
            updated += 1

    logger.info(f"Updated confirmed scores for {updated} keywords")
    return updated


def run_full_fetch(app_id: int) -> dict:
    """
    Master function — fetch campaigns, keyword reports, and update keyword scores.

    Args:
        app_id: iTunes numeric app ID of the target app.

    Returns:
        Summary dict with counts of campaigns, keyword rows, and updated scores.
    """
    end_date   = str(date.today())
    start_date = str(date.today() - timedelta(days=config.SEARCH_ADS_LOOKBACK_DAYS))

    campaigns = fetch_campaigns(app_id)
    if not campaigns:
        logger.warning("No Search Ads campaigns found — skipping keyword report fetch")
        return {"campaigns": 0, "keywords": 0, "updated": 0}

    all_keyword_rows = []
    for campaign in campaigns:
        rows = fetch_keyword_report(campaign["campaign_id"], start_date, end_date)
        all_keyword_rows.extend(rows)

    updated = update_keyword_scores(app_id)

    logger.info(
        f"Search Ads fetch complete — "
        f"{len(campaigns)} campaigns, "
        f"{len(all_keyword_rows)} keyword rows, "
        f"{updated} scores updated"
    )
    return {
        "campaigns": len(campaigns),
        "keywords":  len(all_keyword_rows),
        "updated":   updated,
    }
