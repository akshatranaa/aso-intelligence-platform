from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from datetime import datetime

import psycopg2
import psycopg2.extras

import config

logger = logging.getLogger(__name__)

DATABASE_URL = os.environ.get("DATABASE_URL")


@contextmanager
def get_connection():
    """
    Yield a Postgres connection with auto-commit on success and rollback on error.

    Returns rows as dict-like objects via RealDictCursor. Foreign keys are
    always enforced by Postgres, no pragma needed.
    """
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def create_tables() -> None:
    """
    Create all 6 database tables if they do not already exist.

    Safe to call multiple times — uses CREATE TABLE IF NOT EXISTS throughout.
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS apps (
                app_id              BIGINT PRIMARY KEY,
                name                TEXT NOT NULL,
                description         TEXT,
                release_notes       TEXT,
                category            TEXT,
                avg_rating          REAL,
                rating_count        INTEGER,
                price               REAL DEFAULT 0.0,
                seller_name         TEXT,
                bundle_id           TEXT,
                min_os_version      TEXT,
                version             TEXT,
                country             TEXT DEFAULT 'us',
                is_target_app       INTEGER DEFAULT 0,
                competitor_tier     TEXT,
                competitor_score    REAL,
                collected_at        TEXT NOT NULL
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS reviews (
                review_id           SERIAL PRIMARY KEY,
                app_id              BIGINT NOT NULL,
                review_text         TEXT,
                rating              INTEGER,
                review_date         TEXT,
                author              TEXT,
                sentiment_score     REAL,
                sentiment_label     TEXT,
                theme_cluster       INTEGER,
                collected_at        TEXT NOT NULL,
                FOREIGN KEY (app_id) REFERENCES apps(app_id),
                UNIQUE (app_id, review_date, author)
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS keywords (
                id                  SERIAL PRIMARY KEY,
                app_id              BIGINT NOT NULL,
                keyword             TEXT NOT NULL,
                proxy_volume        REAL,
                proxy_difficulty    REAL,
                proxy_opportunity   REAL,
                confirmed_volume    REAL,
                confirmed_conversion REAL,
                confirmed_cpi       REAL,
                revised_opportunity REAL,
                keyword_bucket      TEXT,
                is_hidden_gem       INTEGER DEFAULT 0,
                is_gap_keyword      INTEGER DEFAULT 0,
                gap_competitor      TEXT,
                source              TEXT,
                created_at          TEXT NOT NULL,
                updated_at          TEXT NOT NULL,
                FOREIGN KEY (app_id) REFERENCES apps(app_id)
            )
        """)
        cursor.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_keywords_app_keyword
            ON keywords (app_id, keyword)
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS rankings (
                id                  SERIAL PRIMARY KEY,
                app_id              BIGINT NOT NULL,
                keyword             TEXT NOT NULL,
                rank                INTEGER,
                date                TEXT NOT NULL,
                rank_delta          INTEGER,
                rank_velocity       REAL,
                FOREIGN KEY (app_id) REFERENCES apps(app_id)
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS search_ads_campaigns (
                campaign_id         TEXT PRIMARY KEY,
                app_id              BIGINT NOT NULL,
                name                TEXT,
                bucket_type         TEXT,
                start_date          TEXT,
                end_date            TEXT,
                total_budget        REAL,
                daily_budget        REAL,
                status              TEXT DEFAULT 'active',
                created_at          TEXT NOT NULL,
                FOREIGN KEY (app_id) REFERENCES apps(app_id)
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS search_ads_keyword_data (
                id                  SERIAL PRIMARY KEY,
                campaign_id         TEXT NOT NULL,
                keyword             TEXT NOT NULL,
                date                TEXT NOT NULL,
                impressions         INTEGER DEFAULT 0,
                taps                INTEGER DEFAULT 0,
                installs            INTEGER DEFAULT 0,
                spend               REAL DEFAULT 0.0,
                avg_cpt             REAL,
                avg_cpi             REAL,
                tap_through_rate    REAL,
                conversion_rate     REAL,
                impression_share    REAL,
                is_search_match     INTEGER DEFAULT 0,
                FOREIGN KEY (campaign_id) REFERENCES search_ads_campaigns(campaign_id),
                UNIQUE (campaign_id, keyword, date)
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS competitors (
                id                  SERIAL PRIMARY KEY,
                target_app_id       BIGINT NOT NULL,
                competitor_app_id   BIGINT NOT NULL,
                tier                TEXT,
                score               REAL,
                discovered_at       TEXT NOT NULL,
                FOREIGN KEY (target_app_id) REFERENCES apps(app_id),
                FOREIGN KEY (competitor_app_id) REFERENCES apps(app_id),
                UNIQUE (target_app_id, competitor_app_id)
            )
        """)
    logger.info("All database tables created (or already exist)")


def save_app(app_dict: dict) -> None:
    """
    Insert an app row, or refresh its metadata if it already exists.

    On conflict the objective metadata (name, ratings, description, country,
    etc.) is refreshed so re-collecting an app updates stale values. The
    is_target_app flag is kept "sticky" via GREATEST — a competitor re-save
    (0) never demotes an existing target (1), but a target-save (1) promotes a
    former competitor. The vestigial competitor_tier/competitor_score columns
    (now owned by the competitors join table) are left untouched.

    Args:
        app_dict: Dict whose keys match apps table column names exactly.
    """
    collected_at = app_dict.get("collected_at", datetime.now().isoformat())
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO apps (
                app_id, name, description, release_notes, category,
                avg_rating, rating_count, price, seller_name, bundle_id,
                min_os_version, version, country, is_target_app,
                competitor_tier, competitor_score, collected_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (app_id) DO UPDATE SET
                name           = EXCLUDED.name,
                description    = EXCLUDED.description,
                release_notes  = EXCLUDED.release_notes,
                category       = EXCLUDED.category,
                avg_rating     = EXCLUDED.avg_rating,
                rating_count   = EXCLUDED.rating_count,
                price          = EXCLUDED.price,
                seller_name    = EXCLUDED.seller_name,
                bundle_id      = EXCLUDED.bundle_id,
                min_os_version = EXCLUDED.min_os_version,
                version        = EXCLUDED.version,
                country        = EXCLUDED.country,
                collected_at   = EXCLUDED.collected_at,
                is_target_app  = GREATEST(apps.is_target_app, EXCLUDED.is_target_app)
            """,
            (
                app_dict["app_id"],
                app_dict["name"],
                app_dict.get("description"),
                app_dict.get("release_notes"),
                app_dict.get("category"),
                app_dict.get("avg_rating"),
                app_dict.get("rating_count"),
                app_dict.get("price", 0.0),
                app_dict.get("seller_name"),
                app_dict.get("bundle_id"),
                app_dict.get("min_os_version"),
                app_dict.get("version"),
                app_dict.get("country", config.DEFAULT_COUNTRY),
                app_dict.get("is_target_app", 0),
                app_dict.get("competitor_tier"),
                app_dict.get("competitor_score"),
                collected_at,
            ),
        )


def save_reviews(reviews_list: list[dict]) -> int:
    """
    Bulk insert reviews into the reviews table, skipping duplicates silently.

    Duplicate detection uses the UNIQUE constraint on (app_id, review_date, author).

    Args:
        reviews_list: List of dicts with review fields.

    Returns:
        Count of reviews actually inserted.
    """
    inserted_count = 0
    with get_connection() as conn:
        cursor = conn.cursor()
        for review in reviews_list:
            cursor.execute(
                """
                INSERT INTO reviews (
                    app_id, review_text, rating, review_date,
                    author, sentiment_score, sentiment_label,
                    theme_cluster, collected_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (app_id, review_date, author) DO NOTHING
                """,
                (
                    review["app_id"],
                    review.get("review_text"),
                    review.get("rating"),
                    review.get("review_date"),
                    review.get("author"),
                    review.get("sentiment_score"),
                    review.get("sentiment_label"),
                    review.get("theme_cluster"),
                    review.get("collected_at", datetime.now().isoformat()),
                ),
            )
            inserted_count += cursor.rowcount
    return inserted_count


def save_ranking(app_id: int, keyword: str, rank: int | None, date: str) -> None:
    """
    Insert one ranking row, computing rank_delta against the previous record.

    A None rank (app not in the top results) is stored as a NULL row so an
    explicitly tracked keyword still persists and shows as "Unranked" instead
    of vanishing.

    Idempotent per day: any existing snapshot for the same date is replaced, so
    re-collecting or hitting the refresh button multiple times a day updates
    that day's row rather than appending duplicates.

    Args:
        app_id:  iTunes numeric app ID.
        keyword: Keyword that was searched.
        rank:    Position found (1-indexed; 1 = top result), or None if unranked.
        date:    Date string in YYYY-MM-DD format.
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        # Replace any snapshot already recorded for this keyword today.
        cursor.execute(
            "DELETE FROM rankings WHERE app_id = %s AND keyword = %s AND date = %s",
            (app_id, keyword, date),
        )
        # rank_delta is measured against the most recent earlier day (None when
        # unranked, when there is no prior history, or when the last day was NULL).
        cursor.execute(
            """
            SELECT rank FROM rankings
            WHERE app_id = %s AND keyword = %s
            ORDER BY date DESC LIMIT 1
            """,
            (app_id, keyword),
        )
        prev = cursor.fetchone()
        yesterday_rank = prev["rank"] if prev else None
        rank_delta = (
            rank - yesterday_rank
            if rank is not None and yesterday_rank is not None
            else None
        )
        cursor.execute(
            """
            INSERT INTO rankings (app_id, keyword, rank, date, rank_delta)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (app_id, keyword, rank, date, rank_delta),
        )
    logger.info(
        f"Saved ranking: app={app_id} keyword='{keyword}' rank={rank} delta={rank_delta}"
    )


def get_app(app_id: int) -> dict | None:
    """
    Fetch one app row by app_id.

    Args:
        app_id: iTunes numeric app ID.

    Returns:
        Dict of app fields, or None if not found.
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM apps WHERE app_id = %s", (app_id,))
        row = cursor.fetchone()
    return dict(row) if row else None


def get_all_apps() -> list[dict]:
    """
    Fetch all rows from the apps table.

    Returns:
        List of dicts, one per app row.
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM apps")
        rows = cursor.fetchall()
    return [dict(row) for row in rows]


def get_reviews(app_id: int) -> list[dict]:
    """
    Fetch all reviews for a given app.

    Args:
        app_id: iTunes numeric app ID.

    Returns:
        List of review dicts.
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM reviews WHERE app_id = %s", (app_id,))
        rows = cursor.fetchall()
    return [dict(row) for row in rows]


def get_all_rankings(app_id: int) -> list[dict]:
    """
    Fetch all ranking rows for an app across every keyword.

    Args:
        app_id: iTunes numeric app ID.

    Returns:
        List of ranking dicts ordered oldest-first.
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM rankings WHERE app_id = %s ORDER BY date ASC",
            (app_id,),
        )
        rows = cursor.fetchall()
    return [dict(row) for row in rows]


def get_rankings(app_id: int, keyword: str) -> list[dict]:
    """
    Fetch all ranking rows for an app+keyword pair, ordered by date ascending.

    Args:
        app_id:  iTunes numeric app ID.
        keyword: Keyword string.

    Returns:
        List of ranking dicts ordered oldest-first.
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT * FROM rankings
            WHERE app_id = %s AND keyword = %s
            ORDER BY date ASC
            """,
            (app_id, keyword),
        )
        rows = cursor.fetchall()
    return [dict(row) for row in rows]


def app_exists(app_id: int) -> bool:
    """
    Check whether an app_id is present in the apps table.

    Args:
        app_id: iTunes numeric app ID.

    Returns:
        True if the app exists, False otherwise.
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM apps WHERE app_id = %s", (app_id,))
        row = cursor.fetchone()
    return row is not None


def get_yesterday_rank(app_id: int, keyword: str) -> int | None:
    """
    Fetch the most recent rank recorded for an app+keyword pair.

    Args:
        app_id:  iTunes numeric app ID.
        keyword: Keyword string.

    Returns:
        Most recent rank value, or None if no previous record exists.
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT rank FROM rankings
            WHERE app_id = %s AND keyword = %s
            ORDER BY date DESC
            LIMIT 1
            """,
            (app_id, keyword),
        )
        row = cursor.fetchone()
    return row["rank"] if row else None


def get_keywords(app_id: int) -> list[dict]:
    """
    Fetch all keyword rows for a given app.

    Args:
        app_id: iTunes numeric app ID.

    Returns:
        List of dicts, one per keyword row.
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM keywords WHERE app_id = %s", (app_id,))
        rows = cursor.fetchall()
    return [dict(row) for row in rows]


def save_keyword(keyword_dict: dict) -> None:
    """
    Insert or replace one keyword row in the keywords table.

    Args:
        keyword_dict: Dict whose keys match the keywords table columns.
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO keywords (
                app_id, keyword, proxy_volume, proxy_difficulty,
                proxy_opportunity, confirmed_volume, confirmed_conversion,
                confirmed_cpi, revised_opportunity, keyword_bucket,
                is_hidden_gem, is_gap_keyword, gap_competitor,
                source, created_at, updated_at
            ) VALUES (
                %(app_id)s, %(keyword)s, %(proxy_volume)s, %(proxy_difficulty)s,
                %(proxy_opportunity)s, %(confirmed_volume)s, %(confirmed_conversion)s,
                %(confirmed_cpi)s, %(revised_opportunity)s, %(keyword_bucket)s,
                %(is_hidden_gem)s, %(is_gap_keyword)s, %(gap_competitor)s,
                %(source)s, %(created_at)s, %(updated_at)s
            )
            ON CONFLICT (app_id, keyword) DO UPDATE SET
                proxy_volume         = EXCLUDED.proxy_volume,
                proxy_difficulty     = EXCLUDED.proxy_difficulty,
                proxy_opportunity    = EXCLUDED.proxy_opportunity,
                confirmed_volume     = EXCLUDED.confirmed_volume,
                confirmed_conversion = EXCLUDED.confirmed_conversion,
                confirmed_cpi        = EXCLUDED.confirmed_cpi,
                revised_opportunity  = EXCLUDED.revised_opportunity,
                keyword_bucket       = EXCLUDED.keyword_bucket,
                is_hidden_gem        = EXCLUDED.is_hidden_gem,
                is_gap_keyword       = EXCLUDED.is_gap_keyword,
                gap_competitor       = EXCLUDED.gap_competitor,
                source               = EXCLUDED.source,
                updated_at           = EXCLUDED.updated_at
            """,
            keyword_dict,
        )
    logger.info(f"Saved keyword: '{keyword_dict['keyword']}' for app {keyword_dict['app_id']}")


def update_sentiment(review_id: int, score: float, label: str) -> None:
    """
    Write VADER sentiment score and label back to a review row.

    Args:
        review_id: Primary key of the review row.
        score:     VADER compound score (-1.0 to +1.0).
        label:     One of "positive", "negative", "neutral".
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE reviews SET sentiment_score = %s, sentiment_label = %s WHERE review_id = %s",
            (score, label, review_id),
        )


def update_sentiment_labels(reviews: list[dict]) -> None:
    """
    Bulk-write sentiment score and label back to many review rows.

    Args:
        reviews: List of scored review dicts, each with review_id,
                 sentiment_score, and sentiment_label.
    """
    if not reviews:
        return
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.executemany(
            """
            UPDATE reviews
            SET sentiment_score = %s, sentiment_label = %s
            WHERE review_id = %s
            """,
            [
                (r["sentiment_score"], r["sentiment_label"], r["review_id"])
                for r in reviews
            ],
        )


def update_rank_velocity(ranking_id: int, velocity: float) -> None:
    """
    Write a computed rank velocity back to one ranking row.

    Args:
        ranking_id: Primary key (id) of the ranking row.
        velocity:   Mean rank change per day.
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE rankings SET rank_velocity = %s WHERE id = %s",
            (velocity, ranking_id),
        )


def update_keyword_confirmed_scores(
    app_id: int,
    keyword: str,
    confirmed_volume: float,
    confirmed_conversion: float,
    confirmed_cpi: float,
    revised_opportunity: float,
    updated_at: str,
) -> None:
    """
    Write Search Ads confirmed metrics and the revised opportunity to a keyword.

    Args:
        app_id:               iTunes app ID.
        keyword:              Keyword string.
        confirmed_volume:     Confirmed search volume proxy.
        confirmed_conversion: Confirmed conversion rate.
        confirmed_cpi:        Confirmed cost per install.
        revised_opportunity:  Recomputed opportunity score.
        updated_at:           ISO timestamp for the update.
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE keywords
            SET confirmed_volume     = %s,
                confirmed_conversion = %s,
                confirmed_cpi        = %s,
                revised_opportunity  = %s,
                updated_at           = %s
            WHERE app_id = %s AND keyword = %s
            """,
            (
                confirmed_volume,
                confirmed_conversion,
                confirmed_cpi,
                revised_opportunity,
                updated_at,
                app_id,
                keyword,
            ),
        )


def get_competitor_apps() -> list[dict]:
    """
    Fetch all apps that are not the target app.

    Returns:
        List of dicts for every row where is_target_app = 0.
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM apps WHERE is_target_app = 0")
        rows = cursor.fetchall()
    return [dict(row) for row in rows]


def save_competitor(
    target_app_id: int, competitor_app_id: int, tier: str, score: float
) -> None:
    """
    Record (or update) that one app is a scored competitor of a target app.

    Args:
        target_app_id:     The app the competitor was discovered for.
        competitor_app_id: The competing app.
        tier:              "tier1" or "tier2".
        score:             Competitor score in [0.0, 1.0].
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO competitors (
                target_app_id, competitor_app_id, tier, score, discovered_at
            ) VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (target_app_id, competitor_app_id) DO UPDATE SET
                tier          = EXCLUDED.tier,
                score         = EXCLUDED.score,
                discovered_at = EXCLUDED.discovered_at
            """,
            (target_app_id, competitor_app_id, tier, score, datetime.now().isoformat()),
        )


def get_competitors(target_app_id: int) -> list[dict]:
    """
    Fetch competitor apps discovered specifically for one target app.

    Joins the competitors relationship table with app metadata, exposing
    each competitor's tier/score for THIS target as competitor_tier /
    competitor_score (overriding any stale global columns on the app row).

    Args:
        target_app_id: The app to fetch competitors for.

    Returns:
        List of competitor app dicts, sorted by score descending.
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT a.*, c.tier, c.score
            FROM competitors c
            JOIN apps a ON a.app_id = c.competitor_app_id
            WHERE c.target_app_id = %s
            ORDER BY c.score DESC
            """,
            (target_app_id,),
        )
        rows = cursor.fetchall()
    result = []
    for row in rows:
        d = dict(row)
        d["competitor_tier"]  = d.pop("tier")
        d["competitor_score"] = d.pop("score")
        result.append(d)
    return result


def get_target_app() -> dict | None:
    """
    Fetch the single target app row.

    Returns:
        Dict for the target app row, or None if not set yet.
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM apps WHERE is_target_app = 1 LIMIT 1")
        row = cursor.fetchone()
    return dict(row) if row else None


def save_campaign(campaign_dict: dict) -> None:
    """
    Insert or replace one campaign row in the search_ads_campaigns table.

    Args:
        campaign_dict: Dict whose keys match the search_ads_campaigns columns.
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO search_ads_campaigns (
                campaign_id, app_id, name, bucket_type,
                start_date, end_date, total_budget,
                daily_budget, status, created_at
            ) VALUES (
                %(campaign_id)s, %(app_id)s, %(name)s, %(bucket_type)s,
                %(start_date)s, %(end_date)s, %(total_budget)s,
                %(daily_budget)s, %(status)s, %(created_at)s
            )
            ON CONFLICT (campaign_id) DO UPDATE SET
                app_id       = EXCLUDED.app_id,
                name         = EXCLUDED.name,
                bucket_type  = EXCLUDED.bucket_type,
                start_date   = EXCLUDED.start_date,
                end_date     = EXCLUDED.end_date,
                total_budget = EXCLUDED.total_budget,
                daily_budget = EXCLUDED.daily_budget,
                status       = EXCLUDED.status
            """,
            campaign_dict,
        )
    logger.info(f"Saved campaign: '{campaign_dict['name']}' ({campaign_dict['campaign_id']})")


def save_keyword_data(kw_dict: dict) -> None:
    """
    Insert or replace one keyword performance row in search_ads_keyword_data.

    Args:
        kw_dict: Dict whose keys match the search_ads_keyword_data columns.
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO search_ads_keyword_data (
                campaign_id, keyword, date, impressions, taps,
                installs, spend, avg_cpt, avg_cpi,
                tap_through_rate, conversion_rate,
                impression_share, is_search_match
            ) VALUES (
                %(campaign_id)s, %(keyword)s, %(date)s, %(impressions)s, %(taps)s,
                %(installs)s, %(spend)s, %(avg_cpt)s, %(avg_cpi)s,
                %(tap_through_rate)s, %(conversion_rate)s,
                %(impression_share)s, %(is_search_match)s
            )
            ON CONFLICT (campaign_id, keyword, date) DO UPDATE SET
                impressions       = EXCLUDED.impressions,
                taps              = EXCLUDED.taps,
                installs          = EXCLUDED.installs,
                spend             = EXCLUDED.spend,
                avg_cpt           = EXCLUDED.avg_cpt,
                avg_cpi           = EXCLUDED.avg_cpi,
                tap_through_rate  = EXCLUDED.tap_through_rate,
                conversion_rate   = EXCLUDED.conversion_rate,
                impression_share  = EXCLUDED.impression_share,
                is_search_match   = EXCLUDED.is_search_match
            """,
            kw_dict,
        )
    logger.info(f"Saved keyword data: '{kw_dict['keyword']}' for campaign {kw_dict['campaign_id']}")


def get_campaigns(app_id: int) -> list[dict]:
    """
    Fetch all Search Ads campaigns for a given app.

    Args:
        app_id: iTunes numeric app ID.

    Returns:
        List of campaign dicts.
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM search_ads_campaigns WHERE app_id = %s",
            (app_id,),
        )
        rows = cursor.fetchall()
    return [dict(row) for row in rows]


def get_keyword_data(campaign_id: str) -> list[dict]:
    """
    Fetch all keyword performance rows for a given campaign.

    Args:
        campaign_id: Search Ads campaign ID string.

    Returns:
        List of keyword data dicts.
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM search_ads_keyword_data WHERE campaign_id = %s",
            (campaign_id,),
        )
        rows = cursor.fetchall()
    return [dict(row) for row in rows]
