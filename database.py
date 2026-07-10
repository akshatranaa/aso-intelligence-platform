from __future__ import annotations

import json
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
                genres              TEXT,
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
    migrate()


def migrate() -> None:
    """
    Apply idempotent schema migrations for multi-country support.

    Adds a `country` dimension to reviews, rankings, and competitors, backfills
    existing rows from the app's stored country, swaps the unique constraints to
    include country, and creates the per-country app_country_stats table (so each
    (app_id, country) pair is its own analysable entity). Safe to run repeatedly.
    """
    with get_connection() as conn:
        cur = conn.cursor()

        # 1. Add the country column to the per-app data tables.
        cur.execute("ALTER TABLE reviews     ADD COLUMN IF NOT EXISTS country TEXT")
        cur.execute("ALTER TABLE rankings    ADD COLUMN IF NOT EXISTS country TEXT")
        cur.execute("ALTER TABLE competitors ADD COLUMN IF NOT EXISTS country TEXT")

        # 1b. Store the app's full genre list (JSON) so tiering can treat a
        #     q-commerce app as same-category whether Apple filed its primary
        #     genre as Food & Drink or Shopping. Backfilled lazily on next fetch.
        cur.execute("ALTER TABLE apps ADD COLUMN IF NOT EXISTS genres TEXT")

        # 2. Backfill existing rows from the app's stored country (so pre-migration
        #    data keeps working, attributed to whatever it was collected as).
        cur.execute(
            "UPDATE reviews r SET country = COALESCE("
            "(SELECT a.country FROM apps a WHERE a.app_id = r.app_id), 'us') "
            "WHERE r.country IS NULL"
        )
        cur.execute(
            "UPDATE rankings rk SET country = COALESCE("
            "(SELECT a.country FROM apps a WHERE a.app_id = rk.app_id), 'us') "
            "WHERE rk.country IS NULL"
        )
        cur.execute(
            "UPDATE competitors c SET country = COALESCE("
            "(SELECT a.country FROM apps a WHERE a.app_id = c.target_app_id), 'us') "
            "WHERE c.country IS NULL"
        )

        # 3. Swap the unique constraints to include country (backfill above can't
        #    create duplicates — every existing app had a single country).
        cur.execute(
            "ALTER TABLE reviews DROP CONSTRAINT IF EXISTS "
            "reviews_app_id_review_date_author_key"
        )
        cur.execute(
            "DO $$ BEGIN "
            "IF NOT EXISTS (SELECT 1 FROM pg_constraint "
            "WHERE conname='reviews_app_country_date_author_key') THEN "
            "ALTER TABLE reviews ADD CONSTRAINT reviews_app_country_date_author_key "
            "UNIQUE (app_id, country, review_date, author); END IF; END $$;"
        )
        cur.execute(
            "ALTER TABLE competitors DROP CONSTRAINT IF EXISTS "
            "competitors_target_app_id_competitor_app_id_key"
        )
        cur.execute(
            "DO $$ BEGIN "
            "IF NOT EXISTS (SELECT 1 FROM pg_constraint "
            "WHERE conname='competitors_target_country_competitor_key') THEN "
            "ALTER TABLE competitors ADD CONSTRAINT competitors_target_country_competitor_key "
            "UNIQUE (target_app_id, country, competitor_app_id); END IF; END $$;"
        )

        # 4. Per-country app metadata — each (app_id, country) is its own entity.
        cur.execute("""
            CREATE TABLE IF NOT EXISTS app_country_stats (
                app_id        BIGINT NOT NULL,
                country       TEXT NOT NULL,
                name          TEXT,
                rating_count  INTEGER,
                avg_rating    REAL,
                price         REAL,
                version       TEXT,
                description   TEXT,
                collected_at  TEXT,
                PRIMARY KEY (app_id, country),
                FOREIGN KEY (app_id) REFERENCES apps(app_id)
            )
        """)
        # Backfill a stats row for every existing app from its current metadata.
        cur.execute("""
            INSERT INTO app_country_stats
                (app_id, country, name, rating_count, avg_rating, price,
                 version, description, collected_at)
            SELECT app_id, country, name, rating_count, avg_rating, price,
                   version, description, collected_at
            FROM apps
            ON CONFLICT (app_id, country) DO NOTHING
        """)

        # 5. Seed keywords used for competitor discovery, editable per (app,
        #    country). Backfilled best-effort from existing tracked ranking
        #    keywords so already-collected apps show a seed list immediately.
        cur.execute("""
            CREATE TABLE IF NOT EXISTS seed_keywords (
                app_id   BIGINT NOT NULL,
                country  TEXT NOT NULL,
                keyword  TEXT NOT NULL,
                PRIMARY KEY (app_id, country, keyword),
                FOREIGN KEY (app_id) REFERENCES apps(app_id)
            )
        """)
        cur.execute("""
            INSERT INTO seed_keywords (app_id, country, keyword)
            SELECT DISTINCT app_id, country, keyword FROM rankings
            WHERE app_id IN (SELECT app_id FROM apps WHERE is_target_app = 1)
            ON CONFLICT (app_id, country, keyword) DO NOTHING
        """)

        # 6. Which seed keyword surfaced which kept competitor, per (app,
        #    country). Lets a seed removal drop only the competitors unique to
        #    that keyword instead of re-running the whole discovery. No backfill:
        #    the first seed edit on a pre-existing app rebuilds this map once.
        cur.execute("""
            CREATE TABLE IF NOT EXISTS competitor_seeds (
                target_app_id      BIGINT NOT NULL,
                country            TEXT NOT NULL,
                keyword            TEXT NOT NULL,
                competitor_app_id  BIGINT NOT NULL,
                PRIMARY KEY (target_app_id, country, keyword, competitor_app_id),
                FOREIGN KEY (target_app_id) REFERENCES apps(app_id),
                FOREIGN KEY (competitor_app_id) REFERENCES apps(app_id)
            )
        """)
    logger.info("Multi-country migration applied (idempotent)")


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
                app_id, name, description, release_notes, category, genres,
                avg_rating, rating_count, price, seller_name, bundle_id,
                min_os_version, version, country, is_target_app,
                competitor_tier, competitor_score, collected_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (app_id) DO UPDATE SET
                name           = EXCLUDED.name,
                description    = EXCLUDED.description,
                release_notes  = EXCLUDED.release_notes,
                category       = EXCLUDED.category,
                genres         = EXCLUDED.genres,
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
                # Store NULL (not "[]") when absent so it re-fetches next time.
                json.dumps(app_dict["genres"]) if app_dict.get("genres") else None,
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
    # Also snapshot this app's metadata for its country, so each (app, country)
    # keeps its own rating count / version / description independently.
    stats = dict(app_dict)
    stats["collected_at"] = collected_at
    save_app_country_stats(stats)


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
                    app_id, country, review_text, rating, review_date,
                    author, sentiment_score, sentiment_label,
                    theme_cluster, collected_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (app_id, country, review_date, author) DO NOTHING
                """,
                (
                    review["app_id"],
                    review.get("country", config.DEFAULT_COUNTRY),
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


def save_ranking(
    app_id: int, keyword: str, rank: int | None, date: str,
    country: str = config.DEFAULT_COUNTRY,
) -> None:
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
        country: App Store country the rank was fetched in.
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        # Replace any snapshot already recorded for this keyword+country today.
        cursor.execute(
            "DELETE FROM rankings WHERE app_id = %s AND keyword = %s "
            "AND date = %s AND country = %s",
            (app_id, keyword, date, country),
        )
        # rank_delta is measured against the most recent earlier day (None when
        # unranked, when there is no prior history, or when the last day was NULL).
        cursor.execute(
            """
            SELECT rank FROM rankings
            WHERE app_id = %s AND keyword = %s AND country = %s
            ORDER BY date DESC LIMIT 1
            """,
            (app_id, keyword, country),
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
            INSERT INTO rankings (app_id, keyword, rank, date, rank_delta, country)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (app_id, keyword, rank, date, rank_delta, country),
        )
    logger.info(
        f"Saved ranking: app={app_id} keyword='{keyword}' rank={rank} "
        f"delta={rank_delta} [{country}]"
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


def get_reviews(app_id: int, country: str | None = None) -> list[dict]:
    """
    Fetch reviews for a given app, optionally scoped to one country.

    Args:
        app_id:  iTunes numeric app ID.
        country: If given, only reviews collected for that App Store country.

    Returns:
        List of review dicts.
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        if country is None:
            cursor.execute("SELECT * FROM reviews WHERE app_id = %s", (app_id,))
        else:
            cursor.execute(
                "SELECT * FROM reviews WHERE app_id = %s AND country = %s",
                (app_id, country),
            )
        rows = cursor.fetchall()
    return [dict(row) for row in rows]


def get_all_rankings(app_id: int, country: str | None = None) -> list[dict]:
    """
    Fetch all ranking rows for an app across every keyword.

    Args:
        app_id:  iTunes numeric app ID.
        country: If given, only rankings for that App Store country.

    Returns:
        List of ranking dicts ordered oldest-first.
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        if country is None:
            cursor.execute(
                "SELECT * FROM rankings WHERE app_id = %s ORDER BY date ASC",
                (app_id,),
            )
        else:
            cursor.execute(
                "SELECT * FROM rankings WHERE app_id = %s AND country = %s "
                "ORDER BY date ASC",
                (app_id, country),
            )
        rows = cursor.fetchall()
    return [dict(row) for row in rows]


def get_rankings(app_id: int, keyword: str, country: str | None = None) -> list[dict]:
    """
    Fetch all ranking rows for an app+keyword pair, ordered by date ascending.

    Args:
        app_id:  iTunes numeric app ID.
        keyword: Keyword string.
        country: If given, only rankings for that App Store country.

    Returns:
        List of ranking dicts ordered oldest-first.
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        if country is None:
            cursor.execute(
                "SELECT * FROM rankings WHERE app_id = %s AND keyword = %s "
                "ORDER BY date ASC",
                (app_id, keyword),
            )
        else:
            cursor.execute(
                "SELECT * FROM rankings WHERE app_id = %s AND keyword = %s "
                "AND country = %s ORDER BY date ASC",
                (app_id, keyword, country),
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
    target_app_id: int, competitor_app_id: int, tier: str, score: float,
    country: str = config.DEFAULT_COUNTRY,
) -> None:
    """
    Record (or update) that one app is a scored competitor of a target app.

    Args:
        target_app_id:     The app the competitor was discovered for.
        competitor_app_id: The competing app.
        tier:              "tier1" or "tier2".
        score:             Competitor score in [0.0, 1.0].
        country:           App Store country the competitor was discovered in.
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO competitors (
                target_app_id, competitor_app_id, tier, score, discovered_at, country
            ) VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (target_app_id, country, competitor_app_id) DO UPDATE SET
                tier          = EXCLUDED.tier,
                score         = EXCLUDED.score,
                discovered_at = EXCLUDED.discovered_at
            """,
            (target_app_id, competitor_app_id, tier, score,
             datetime.now().isoformat(), country),
        )


def get_competitors(target_app_id: int, country: str | None = None) -> list[dict]:
    """
    Fetch competitor apps discovered specifically for one target app.

    Joins the competitors relationship table with app metadata, exposing
    each competitor's tier/score for THIS target as competitor_tier /
    competitor_score (overriding any stale global columns on the app row).

    Args:
        target_app_id: The app to fetch competitors for.
        country:       If given, only competitors discovered for that country.

    Returns:
        List of competitor app dicts, sorted by score descending.
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        if country is None:
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
        else:
            cursor.execute(
                """
                SELECT a.*, c.tier, c.score
                FROM competitors c
                JOIN apps a ON a.app_id = c.competitor_app_id
                WHERE c.target_app_id = %s AND c.country = %s
                ORDER BY c.score DESC
                """,
                (target_app_id, country),
            )
        rows = cursor.fetchall()
    result = []
    for row in rows:
        d = dict(row)
        d["competitor_tier"]  = d.pop("tier")
        d["competitor_score"] = d.pop("score")
        result.append(d)
    return result


def untrack_app(app_id: int) -> None:
    """
    Remove an app from the tracked-apps list without deleting its data.

    Sets is_target_app = 0 so it drops out of GET /apps, while its reviews,
    rankings, competitors, and per-country stats remain in the database (a later
    collect re-promotes it).

    Args:
        app_id: iTunes numeric app ID.
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE apps SET is_target_app = 0 WHERE app_id = %s", (app_id,)
        )
    logger.info(f"Untracked app {app_id} (data retained)")


def delete_ranking_keyword(app_id: int, keyword: str, country: str) -> int:
    """
    Stop tracking a keyword — delete its ranking rows for an app+country.

    Args:
        app_id:  iTunes numeric app ID.
        keyword: Keyword to remove.
        country: App Store country code.

    Returns:
        Number of ranking rows deleted.
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM rankings WHERE app_id = %s AND keyword = %s AND country = %s",
            (app_id, keyword, country),
        )
        deleted = cursor.rowcount
    logger.info(f"Deleted {deleted} ranking rows for '{keyword}' (app {app_id} [{country}])")
    return deleted


def delete_competitor(
    target_app_id: int, competitor_app_id: int, country: str
) -> bool:
    """
    Remove a competitor from a target's list, purging the app row if orphaned.

    Always deletes the competitors join row for this target+country. Then, if the
    competitor app is safe to fully remove — it is not a target app and is not
    referenced by any other competitor relationship, review, ranking, or keyword —
    its apps and app_country_stats rows are deleted too, so junk competitors leave
    the database entirely. Shared apps (e.g. one that is also a target, or a
    competitor of another app) keep their row; only the relationship is removed.

    Args:
        target_app_id:     The app the competitor belongs to.
        competitor_app_id: The competitor to remove.
        country:           App Store country the relationship was discovered for.

    Returns:
        True if the competitor's app row was fully purged, False if only the
        relationship was removed (the app is still referenced elsewhere).
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM competitors WHERE target_app_id = %s "
            "AND competitor_app_id = %s AND country = %s",
            (target_app_id, competitor_app_id, country),
        )
        # Drop this competitor's seed-map rows so no removed keyword still
        # "owns" a competitor that no longer exists for this target.
        cursor.execute(
            "DELETE FROM competitor_seeds WHERE target_app_id = %s "
            "AND competitor_app_id = %s AND country = %s",
            (target_app_id, competitor_app_id, country),
        )

        # Only purge the app row if nothing else references it.
        cursor.execute(
            "SELECT is_target_app FROM apps WHERE app_id = %s", (competitor_app_id,)
        )
        row = cursor.fetchone()
        if not row or row["is_target_app"] == 1:
            return False

        references = [
            ("competitors", "competitor_app_id"),
            ("competitors", "target_app_id"),
            ("reviews", "app_id"),
            ("rankings", "app_id"),
            ("keywords", "app_id"),
        ]
        for table, column in references:
            cursor.execute(
                f"SELECT 1 FROM {table} WHERE {column} = %s LIMIT 1",
                (competitor_app_id,),
            )
            if cursor.fetchone():
                return False

        cursor.execute(
            "DELETE FROM app_country_stats WHERE app_id = %s", (competitor_app_id,)
        )
        cursor.execute("DELETE FROM apps WHERE app_id = %s", (competitor_app_id,))
    logger.info(f"Purged orphaned competitor app {competitor_app_id}")
    return True


def get_seed_keywords(app_id: int, country: str) -> list[str]:
    """
    Return the competitor-discovery seed keywords for an app+country.

    Args:
        app_id:  iTunes numeric app ID.
        country: App Store country code.

    Returns:
        Sorted list of seed keyword strings (empty if none recorded).
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT keyword FROM seed_keywords WHERE app_id = %s AND country = %s "
            "ORDER BY keyword",
            (app_id, country),
        )
        rows = cursor.fetchall()
    return [row["keyword"] for row in rows]


def set_seed_keywords(app_id: int, country: str, keywords: list[str]) -> None:
    """
    Replace the seed keyword list for an app+country.

    Args:
        app_id:   iTunes numeric app ID.
        country:  App Store country code.
        keywords: The complete new seed keyword list.
    """
    cleaned = list(dict.fromkeys(k.strip() for k in keywords if k and k.strip()))
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM seed_keywords WHERE app_id = %s AND country = %s",
            (app_id, country),
        )
        for kw in cleaned:
            cursor.execute(
                "INSERT INTO seed_keywords (app_id, country, keyword) "
                "VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                (app_id, country, kw),
            )
    logger.info(f"Set {len(cleaned)} seed keywords for app {app_id} [{country}]")


def delete_all_competitors(target_app_id: int, country: str) -> int:
    """
    Delete every competitor relationship for a target+country (for re-analysis).

    Only removes the competitors join rows; competitor app rows are left in place
    (they are re-saved by the following discovery, and shared apps must survive).

    Args:
        target_app_id: The target app.
        country:       App Store country code.

    Returns:
        Number of relationship rows deleted.
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM competitors WHERE target_app_id = %s AND country = %s",
            (target_app_id, country),
        )
        deleted = cursor.rowcount
        cursor.execute(
            "DELETE FROM competitor_seeds WHERE target_app_id = %s AND country = %s",
            (target_app_id, country),
        )
    logger.info(f"Cleared {deleted} competitors for app {target_app_id} [{country}]")
    return deleted


def record_competitor_seeds(
    target_app_id: int, country: str, mappings: list[tuple[str, int]]
) -> None:
    """
    Record which seed keywords surfaced which kept competitors.

    Args:
        target_app_id: The target app.
        country:       App Store country code.
        mappings:      (keyword, competitor_app_id) pairs to record.
    """
    if not mappings:
        return
    with get_connection() as conn:
        cursor = conn.cursor()
        for keyword, competitor_app_id in mappings:
            cursor.execute(
                "INSERT INTO competitor_seeds "
                "(target_app_id, country, keyword, competitor_app_id) "
                "VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING",
                (target_app_id, country, keyword, competitor_app_id),
            )


def delete_competitor_seed_keyword(
    target_app_id: int, country: str, keyword: str
) -> None:
    """
    Remove all seed-map rows for one keyword (used when a seed is deleted).

    This does not delete any competitor rows — the caller decides which
    competitors are now orphaned via get_orphaned_competitors.

    Args:
        target_app_id: The target app.
        country:       App Store country code.
        keyword:       The seed keyword being removed.
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM competitor_seeds WHERE target_app_id = %s "
            "AND country = %s AND keyword = %s",
            (target_app_id, country, keyword),
        )


def clear_competitor_seed_map(target_app_id: int, country: str) -> None:
    """
    Remove all seed→competitor map rows for a target+country.

    Called at the start of a full discovery so the rebuilt map reflects only the
    current run (incremental seed edits never clear the whole map).

    Args:
        target_app_id: The target app.
        country:       App Store country code.
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM competitor_seeds WHERE target_app_id = %s AND country = %s",
            (target_app_id, country),
        )


def get_orphaned_competitors(target_app_id: int, country: str) -> list[int]:
    """
    Return competitors for a target+country with no remaining seed-map row.

    After deleting a seed keyword's mappings, these are the competitors that no
    surviving keyword surfaces — safe to remove.

    Args:
        target_app_id: The target app.
        country:       App Store country code.

    Returns:
        List of competitor app IDs that are no longer mapped to any seed.
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT c.competitor_app_id AS id
            FROM competitors c
            WHERE c.target_app_id = %s AND c.country = %s
              AND NOT EXISTS (
                SELECT 1 FROM competitor_seeds s
                WHERE s.target_app_id = c.target_app_id
                  AND s.country = c.country
                  AND s.competitor_app_id = c.competitor_app_id
              )
            """,
            (target_app_id, country),
        )
        rows = cursor.fetchall()
    return [row["id"] for row in rows]


def competitor_map_needs_rebuild(target_app_id: int, country: str) -> bool:
    """
    Whether the seed→competitor map is incomplete and needs a full rebuild.

    True when competitors exist but at least one has no seed-map row — i.e. an
    app collected before this feature, or a partially-mapped state. When there
    are no competitors the map is trivially complete (additions will populate it).

    Args:
        target_app_id: The target app.
        country:       App Store country code.

    Returns:
        True if the next seed edit must do a full rebuild to repopulate the map.
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) AS n FROM competitors "
            "WHERE target_app_id = %s AND country = %s",
            (target_app_id, country),
        )
        if cursor.fetchone()["n"] == 0:
            return False
    return len(get_orphaned_competitors(target_app_id, country)) > 0


def get_competitors_last_discovered(target_app_id: int, country: str) -> str | None:
    """
    Return when competitors were most recently discovered for a target+country.

    Args:
        target_app_id: The target app.
        country:       App Store country code.

    Returns:
        The latest discovered_at ISO timestamp string, or None if never run.
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT MAX(discovered_at) AS last FROM competitors "
            "WHERE target_app_id = %s AND country = %s",
            (target_app_id, country),
        )
        row = cursor.fetchone()
    return row["last"] if row else None


def get_app_countries(app_id: int) -> list[str]:
    """
    Return the App Store countries this app has been collected for.

    Args:
        app_id: iTunes numeric app ID.

    Returns:
        Sorted list of two-letter country codes (empty if never collected).
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT country FROM app_country_stats WHERE app_id = %s ORDER BY country",
            (app_id,),
        )
        rows = cursor.fetchall()
    return [row["country"] for row in rows]


def save_app_country_stats(app_dict: dict) -> None:
    """
    Upsert the per-country metadata snapshot for an app (one row per country).

    Args:
        app_dict: App metadata dict with app_id, country, and the metric fields.
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO app_country_stats
                (app_id, country, name, rating_count, avg_rating, price,
                 version, description, collected_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (app_id, country) DO UPDATE SET
                name         = EXCLUDED.name,
                rating_count = EXCLUDED.rating_count,
                avg_rating   = EXCLUDED.avg_rating,
                price        = EXCLUDED.price,
                version      = EXCLUDED.version,
                description  = EXCLUDED.description,
                collected_at = EXCLUDED.collected_at
            """,
            (
                app_dict["app_id"],
                app_dict.get("country", config.DEFAULT_COUNTRY),
                app_dict.get("name"),
                app_dict.get("rating_count"),
                app_dict.get("avg_rating"),
                app_dict.get("price"),
                app_dict.get("version"),
                app_dict.get("description"),
                app_dict.get("collected_at", datetime.now().isoformat()),
            ),
        )


def get_app_country_stats(app_id: int, country: str) -> dict | None:
    """
    Fetch the per-country metadata snapshot for an app.

    Args:
        app_id:  iTunes numeric app ID.
        country: Two-letter App Store country code.

    Returns:
        Dict of the per-country metrics, or None if not present.
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM app_country_stats WHERE app_id = %s AND country = %s",
            (app_id, country),
        )
        row = cursor.fetchone()
    return dict(row) if row else None


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
