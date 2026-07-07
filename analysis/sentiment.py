
from __future__ import annotations

import logging

from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

import config
import database
from analysis import llm_analyst

logger = logging.getLogger(__name__)

_analyzer = SentimentIntensityAnalyzer()


def score_all_reviews(
    app_id: int, use_llm: bool = True, country: str | None = None
) -> dict:
    """
    Run the full sentiment pipeline for one app.

    LLM is the primary method when use_llm=True.
    VADER is the fallback when use_llm=False.

    Args:
        app_id:  iTunes app ID.
        use_llm: Whether to use LLM as primary scorer.
        country: If given, only score reviews for that App Store country.

    Returns:
        Dict with aggregate sentiment stats.
    """
    reviews = database.get_reviews(app_id, country)
    if not reviews:
        return _empty_summary(app_id)

    if use_llm:
        scored = _score_with_llm(reviews)
    else:
        scored = _score_with_vader(reviews)

    _save_sentiment_labels(scored)
    summary = _build_summary(scored)
    summary["app_id"] = app_id
    return summary


def _score_with_llm(reviews: list[dict]) -> list[dict]:

    # Step 1: separate obvious from ambiguous immediately
    obvious    = [r for r in reviews if (r.get("rating") or 3) != 3]
    ambiguous  = [r for r in reviews if (r.get("rating") or 3) == 3]

    results = []

    # Step 2: label obvious reviews directly — no LLM needed
    for review in obvious:
        review["sentiment_score"] = None
        review["sentiment_label"] = _label_from_rating(review.get("rating") or 3)
        results.append(review)

    # Step 3: only call LLM for ambiguous 3-star reviews
    if ambiguous:
        batches = [
            ambiguous[i: i + config.LLM_REVIEW_BATCH_SIZE]
            for i in range(0, len(ambiguous), config.LLM_REVIEW_BATCH_SIZE)
        ]
        for batch in batches:
            llm_result = llm_analyst.analyse_reviews(batch, use_llm=True)
            overall = "neutral"
            if llm_result:
                overall = llm_result.get("overall_sentiment", "neutral")
                if overall == "mixed":
                    overall = "neutral"

            for review in batch:
                if llm_result:
                    label = _infer_label_from_llm(
                        text=   (review["review_text"] or "").lower(),
                        rating= review.get("rating") or 3,
                        llm_result=llm_result,
                        overall=overall,
                    )
                else:
                    label = _label_from_rating(review.get("rating") or 3)

                review["sentiment_score"] = None
                review["sentiment_label"] = label
                results.append(review)

    return results


def _infer_label_from_llm(
    text: str,
    rating: int,
    llm_result: dict,
    overall: str,
) -> str:
    """
    Map a batch-level LLM result to one individual review label.

    Uses star rating as primary signal and LLM overall sentiment
    as a tiebreaker for ambiguous 3-star reviews.

    Args:
        text:       Review text lowercased (unused currently, reserved
                    for future keyword matching).
        rating:     Star rating integer 1-5.
        llm_result: Dict returned by llm_analyst.analyse_reviews().
        overall:    overall_sentiment value from llm_result.

    Returns:
        "positive", "negative", or "neutral".
    """
    if rating >= 4:
        return "positive"
    if rating <= 2:
        return "negative"

    # rating == 3 is ambiguous — use LLM overall sentiment to decide
    if overall == "positive":
        return "positive"
    if overall == "negative":
        return "negative"
    return "neutral"


def _label_from_rating(rating: int) -> str:
    """
    Fallback label based purely on star rating.

    Used when the LLM call fails entirely.

    Args:
        rating: Star rating integer 1-5.

    Returns:
        "positive", "negative", or "neutral".
    """
    if rating >= 4:
        return "positive"
    if rating <= 2:
        return "negative"
    return "neutral"


def _empty_summary(app_id: int) -> dict:
    """
    Return a zero-value summary dict when no reviews exist.

    Prevents division by zero in _build_summary.

    Args:
        app_id: iTunes app ID.

    Returns:
        Dict with all counts and percentages set to zero.
    """
    return {
        "app_id":         app_id,
        "total_reviews":  0,
        "positive_count": 0,
        "negative_count": 0,
        "neutral_count":  0,
        "positive_pct":   0.0,
        "negative_pct":   0.0,
        "neutral_pct":    0.0,
        "avg_rating":     0.0,
    }


def _score_with_vader(reviews: list[dict]) -> list[dict]:
    """
    Run VADER sentiment analysis on every review.

    Fallback method used when use_llm=False.

    Args:
        reviews: List of review dicts from database.

    Returns:
        Same list with sentiment_score and sentiment_label added.
    """
    for review in reviews:
        compound = _analyzer.polarity_scores(
            review["review_text"] or ""
        )["compound"]
        review["sentiment_score"] = compound
        review["sentiment_label"] = _label_from_score(compound)
    return reviews


def _label_from_score(compound: float) -> str:
    """
    Convert a VADER compound score to a sentiment label.

    Used by VADER path only.

    Args:
        compound: VADER compound score in [-1.0, +1.0].

    Returns:
        "positive", "negative", or "neutral".
    """
    if compound >= config.SENTIMENT_POSITIVE_THRESHOLD:
        return "positive"
    if compound <= config.SENTIMENT_NEGATIVE_THRESHOLD:
        return "negative"
    return "neutral"


def _save_sentiment_labels(reviews: list[dict]) -> None:
    """
    Write sentiment_score and sentiment_label back to the reviews table.

    Args:
        reviews: List of scored review dicts containing review_id,
                 sentiment_score, and sentiment_label.
    """
    database.update_sentiment_labels(reviews)
    logger.info(f"Saved sentiment labels for {len(reviews)} reviews")


def _build_summary(reviews: list[dict]) -> dict:
    """
    Compute aggregate sentiment statistics from scored reviews.

    Args:
        reviews: List of review dicts with sentiment_label and rating fields.

    Returns:
        Dict with counts, percentages, and average rating.
    """
    total    = len(reviews)
    positive = sum(1 for r in reviews if r["sentiment_label"] == "positive")
    negative = sum(1 for r in reviews if r["sentiment_label"] == "negative")
    neutral  = sum(1 for r in reviews if r["sentiment_label"] == "neutral")
    avg_rating = (
        sum(r["rating"] for r in reviews if r["rating"]) / total
        if total else 0.0
    )
    return {
        "total_reviews":  total,
        "positive_count": positive,
        "negative_count": negative,
        "neutral_count":  neutral,
        "positive_pct":   round(positive / total * 100, 1) if total else 0.0,
        "negative_pct":   round(negative / total * 100, 1) if total else 0.0,
        "neutral_pct":    round(neutral  / total * 100, 1) if total else 0.0,
        "avg_rating":     round(avg_rating, 2),
    }


def get_sentiment_summary(app_id: int, country: str | None = None) -> dict | None:
    """
    Read already-computed sentiment results from database without recomputing.

    Args:
        app_id:  iTunes app ID.
        country: If given, only reviews collected for that App Store country.

    Returns:
        Aggregate sentiment dict, or None if no scored reviews exist.
    """
    reviews = [
        r for r in database.get_reviews(app_id, country)
        if r["sentiment_label"] is not None
    ]
    if not reviews:
        return None
    return _build_summary(reviews)