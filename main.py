"""ASO Intelligence Platform — orchestration entry point."""

import logging
import sys
from datetime import date, datetime

import config
import database
from analysis import keyword_analysis, rank_tracker, sentiment
from collection import competitor
from collection import scraper

# Step 1 — logging
logging.basicConfig(level=config.LOG_LEVEL, format=config.LOG_FORMAT)
logger = logging.getLogger(__name__)


def main() -> None:
    """Run the full ASO data collection pipeline for a target app."""

    # Step 2 — target app name from CLI
    if len(sys.argv) < 2:
        logger.error("Usage: python main.py <app_name>")
        sys.exit(1)
    target_app_name = sys.argv[1]
    logger.info(f"Starting ASO collection for: {target_app_name}")

    # Step 3 — create tables
    database.create_tables()

    # Step 4 — fetch and save target app
    app_data = scraper.fetch_app_metadata(target_app_name)
    if app_data is None:
        logger.error(f"Could not find app: {target_app_name}")
        sys.exit(1)
    app_data["is_target_app"] = 1
    database.save_app(app_data)
    target_app_id = app_data["app_id"]
    logger.info(f"Target app saved: {app_data['name']} ({target_app_id})")

    # Step 5 — seed keywords derived from the target app itself
    seed_keywords = keyword_analysis.derive_seed_keywords(app_data)
    logger.info(f"Derived seed keywords: {seed_keywords}")

    # Step 6 — discover competitors
    logger.info("Discovering competitors...")
    competitors = competitor.discover_competitors(target_app_id, seed_keywords, max_depth=2)
    tier1 = sum(1 for c in competitors if c["tier"] == "tier1")
    tier2 = sum(1 for c in competitors if c["tier"] == "tier2")
    logger.info(f"Found {len(competitors)} competitors ({tier1} tier1, {tier2} tier2)")

    # Step 7 — record keyword rankings for target app
    logger.info("Recording keyword rankings...")
    today = str(date.today())
    for keyword in seed_keywords:
        rank = scraper.fetch_keyword_ranking(keyword, target_app_id)
        if rank is not None:
            database.save_ranking(target_app_id, keyword, rank, today)
        logger.info(f"Keyword '{keyword}': rank {rank}")

    # Step 8 — fetch and save reviews
    reviews = scraper.fetch_reviews(target_app_id)
    collected_at = datetime.now().isoformat()
    for review in reviews:
        review["collected_at"] = collected_at
        review["app_id"] = target_app_id
    count = database.save_reviews(reviews)
    logger.info(f"Saved {count} reviews")

    # Step 9 — completion summary
    all_apps = database.get_all_apps()
    logger.info("=== Collection complete ===")
    logger.info(f"Apps in database:    {len(all_apps)}")
    logger.info(f"Reviews saved:       {count}")
    logger.info(f"Rankings recorded:   {len(seed_keywords)}")

    # Step 10 — sentiment analysis
    logger.info("Running sentiment analysis...")
    sentiment_summary = sentiment.score_all_reviews(target_app_id, use_llm=False)
    logger.info(
        f"Sentiment: {sentiment_summary['positive_pct']}% positive, "
        f"{sentiment_summary['negative_pct']}% negative, "
        f"{sentiment_summary['neutral_pct']}% neutral"
    )

    # Step 11 — keyword analysis
    logger.info("Running keyword analysis...")
    kw_result = keyword_analysis.run_keyword_analysis(target_app_id, use_llm=False)
    logger.info(
        f"Keywords: {len(kw_result['top_keywords'])} scored, "
        f"{len(kw_result['gaps'])} gaps found"
    )

    # Step 12 — rank tracking
    logger.info("Running rank tracker...")
    rank_tracker.take_snapshot(target_app_id, seed_keywords)
    rank_tracker.compute_all_velocities(target_app_id)
    alerts = rank_tracker.detect_significant_changes(target_app_id, seed_keywords)
    summary = rank_tracker.get_ranking_summary(target_app_id)
    logger.info(f"Rankings recorded with velocity — {len(alerts)} significant changes")
    for entry in summary:
        logger.info(
            f"  '{entry['keyword']}': rank={entry['rank']} "
            f"delta={entry['delta']} trend={entry['trend']}"
        )


if __name__ == "__main__":
    main()
