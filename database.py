from __future__ import annotations

import sqlite3
import logging
from contextlib import contextmanager
from datetime import datetime

import config

logger = logging.getLogger(__name__)


@contextmanager
def get_connection():
    """
    Yield a SQLite connection with auto-commit on success and rollback on error.

    Enforces foreign key constraints and returns rows as dict-like objects.
    """
    conn = sqlite3.connect(config.DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
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
        conn.execute("""
            CREATE TABLE IF NOT EXISTS apps (
                app_id              INTEGER PRIMARY KEY,
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
        conn.execute("""
            CREATE TABLE IF NOT EXISTS reviews (
                review_id           INTEGER PRIMARY KEY AUTOINCREMENT,
                app_id              INTEGER NOT NULL,
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
        conn.execute("""
            CREATE TABLE IF NOT EXISTS keywords (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                app_id              INTEGER NOT NULL,
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
        conn.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_keywords_app_keyword
            ON keywords (app_id, keyword)
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS rankings (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                app_id              INTEGER NOT NULL,
                keyword             TEXT NOT NULL,
                rank                INTEGER,
                date                TEXT NOT NULL,
                rank_delta          INTEGER,
                rank_velocity       REAL,
                FOREIGN KEY (app_id) REFERENCES apps(app_id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS search_ads_campaigns (
                campaign_id         TEXT PRIMARY KEY,
                app_id              INTEGER NOT NULL,
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
        conn.execute("""
            CREATE TABLE IF NOT EXISTS search_ads_keyword_data (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
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
                FOREIGN KEY (campaign_id) REFERENCES search_ads_campaigns(campaign_id)
            )
        """)
    logger.info("All 6 database tables created (or already exist)")


def save_app(app_dict: dict) -> bool:
    """
    Insert one app row, ignoring the insert if app_id already exists.

    Args:
        app_dict: Dict whose keys match apps table column names exactly.

    Returns:
        True if the row was inserted, False if it already existed.
    """
    collected_at = app_dict.get("collected_at", datetime.now().isoformat())
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT OR IGNORE INTO apps (
                app_id, name, description, release_notes, category,
                avg_rating, rating_count, price, seller_name, bundle_id,
                min_os_version, version, country, is_target_app,
                competitor_tier, competitor_score, collected_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
        inserted = cursor.rowcount == 1
    if not inserted:
        logger.warning(f"App {app_dict.get('app_id')} already exists, skipping")
    return inserted


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
        for review in reviews_list:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO reviews (
                    app_id, review_text, rating, review_date,
                    author, sentiment_score, sentiment_label,
                    theme_cluster, collected_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
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


def save_ranking(app_id: int, keyword: str, rank: int, date: str) -> None:
    """
    Insert one ranking row, computing rank_delta against the previous record.

    Args:
        app_id:  iTunes numeric app ID.
        keyword: Keyword that was searched.
        rank:    Position found (1-indexed; 1 = top result).
        date:    Date string in YYYY-MM-DD format.
    """
    yesterday_rank = get_yesterday_rank(app_id, keyword)
    rank_delta = (rank - yesterday_rank) if yesterday_rank is not None else None
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO rankings (app_id, keyword, rank, date, rank_delta)
            VALUES (?, ?, ?, ?, ?)
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
        row = conn.execute(
            "SELECT * FROM apps WHERE app_id = ?", (app_id,)
        ).fetchone()
    return dict(row) if row else None


def get_all_apps() -> list[dict]:
    """
    Fetch all rows from the apps table.

    Returns:
        List of dicts, one per app row.
    """
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM apps").fetchall()
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
        rows = conn.execute(
            "SELECT * FROM reviews WHERE app_id = ?", (app_id,)
        ).fetchall()
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
        rows = conn.execute(
            "SELECT * FROM rankings WHERE app_id = ? ORDER BY date ASC",
            (app_id,),
        ).fetchall()
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
        rows = conn.execute(
            """
            SELECT * FROM rankings
            WHERE app_id = ? AND keyword = ?
            ORDER BY date ASC
            """,
            (app_id, keyword),
        ).fetchall()
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
        row = conn.execute(
            "SELECT 1 FROM apps WHERE app_id = ?", (app_id,)
        ).fetchone()
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
        row = conn.execute(
            """
            SELECT rank FROM rankings
            WHERE app_id = ? AND keyword = ?
            ORDER BY date DESC
            LIMIT 1
            """,
            (app_id, keyword),
        ).fetchone()
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
        rows = conn.execute(
            "SELECT * FROM keywords WHERE app_id = ?", (app_id,)
        ).fetchall()
    return [dict(row) for row in rows]


def save_keyword(keyword_dict: dict) -> None:
    """
    Insert or replace one keyword row in the keywords table.

    Args:
        keyword_dict: Dict whose keys match the keywords table columns.
    """
    with get_connection() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO keywords (
                app_id, keyword, proxy_volume, proxy_difficulty,
                proxy_opportunity, confirmed_volume, confirmed_conversion,
                confirmed_cpi, revised_opportunity, keyword_bucket,
                is_hidden_gem, is_gap_keyword, gap_competitor,
                source, created_at, updated_at
            ) VALUES (
                :app_id, :keyword, :proxy_volume, :proxy_difficulty,
                :proxy_opportunity, :confirmed_volume, :confirmed_conversion,
                :confirmed_cpi, :revised_opportunity, :keyword_bucket,
                :is_hidden_gem, :is_gap_keyword, :gap_competitor,
                :source, :created_at, :updated_at
            )
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
        conn.execute(
            "UPDATE reviews SET sentiment_score = ?, sentiment_label = ? WHERE review_id = ?",
            (score, label, review_id),
        )


def get_competitor_apps() -> list[dict]:
    """
    Fetch all apps that are not the target app.

    Returns:
        List of dicts for every row where is_target_app = 0.
    """
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM apps WHERE is_target_app = 0"
        ).fetchall()
    return [dict(row) for row in rows]


def get_target_app() -> dict | None:
    """
    Fetch the single target app row.

    Returns:
        Dict for the target app row, or None if not set yet.
    """
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM apps WHERE is_target_app = 1 LIMIT 1"
        ).fetchone()
    return dict(row) if row else None


def save_campaign(campaign_dict: dict) -> None:
    """
    Insert or replace one campaign row in the search_ads_campaigns table.

    Args:
        campaign_dict: Dict whose keys match the search_ads_campaigns columns.
    """
    with get_connection() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO search_ads_campaigns (
                campaign_id, app_id, name, bucket_type,
                start_date, end_date, total_budget,
                daily_budget, status, created_at
            ) VALUES (
                :campaign_id, :app_id, :name, :bucket_type,
                :start_date, :end_date, :total_budget,
                :daily_budget, :status, :created_at
            )
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
        conn.execute(
            """
            INSERT OR REPLACE INTO search_ads_keyword_data (
                campaign_id, keyword, date, impressions, taps,
                installs, spend, avg_cpt, avg_cpi,
                tap_through_rate, conversion_rate,
                impression_share, is_search_match
            ) VALUES (
                :campaign_id, :keyword, :date, :impressions, :taps,
                :installs, :spend, :avg_cpt, :avg_cpi,
                :tap_through_rate, :conversion_rate,
                :impression_share, :is_search_match
            )
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
        rows = conn.execute(
            "SELECT * FROM search_ads_campaigns WHERE app_id = ?",
            (app_id,),
        ).fetchall()
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
        rows = conn.execute(
            "SELECT * FROM search_ads_keyword_data WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchall()
    return [dict(row) for row in rows]
