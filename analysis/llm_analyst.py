"""Owns all LLM API calls (via OpenRouter). No other module calls the API directly."""

from __future__ import annotations

import json
import logging
import os

import httpx
from dotenv import load_dotenv

import config

load_dotenv()

logger = logging.getLogger(__name__)


def _call_llm(prompt: str, expect_json: bool = False) -> dict | list | str | None:
    """
    Central function that makes every LLM API call, via OpenRouter.

    Args:
        prompt:      Full prompt string to send.
        expect_json: If True, parse the response text as JSON before returning.

    Returns:
        Parsed JSON dict/list if expect_json=True, raw string otherwise,
        or None if the API call or JSON parse fails.
    """
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        logger.error("OPENROUTER_API_KEY not set — skipping LLM call")
        return None
    try:
        response = httpx.post(
            config.OPENROUTER_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": config.LLM_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": config.LLM_MAX_TOKENS,
            },
            timeout=60.0,
        )
        response.raise_for_status()
        text = response.json()["choices"][0]["message"]["content"]
        if not expect_json:
            return text
        text = text.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        return json.loads(text.strip())
    except Exception as e:
        logger.error(f"LLM API call failed: {e}")
        return None


def analyse_reviews(reviews: list[dict], use_llm: bool = True) -> dict | None:
    """
    Deep analysis of review text to extract structured themes and sentiment.

    Args:
        reviews: List of review dicts with review_text and rating fields.
        use_llm: If False, return None immediately without calling the API.

    Returns:
        Parsed JSON dict with top_complaints, top_praise, overall_sentiment,
        priority_fix, and sentiment_summary keys, or None on failure.
    """
    if not use_llm:
        return None

    formatted = ""
    for i, r in enumerate(reviews[: config.LLM_TOP_REVIEWS]):
        formatted += f"{i + 1}. [{r['rating']} stars] {r['review_text']}\n"

    prompt = f"""
Analyse these {len(reviews)} App Store reviews and return a JSON
object with exactly this structure:
{{
    "top_complaints": [
        {{"theme": "string", "count": int, "example_quote": "string"}},
        ... top 5 complaints
    ],
    "top_praise": [
        {{"theme": "string", "count": int, "example_quote": "string"}},
        ... top 5 praise points
    ],
    "overall_sentiment": "positive" | "negative" | "mixed",
    "priority_fix": "single most important thing to fix based on reviews",
    "sentiment_summary": "2-3 sentence plain English summary"
}}

Reviews:
{formatted}

Return only the JSON object, no other text.
"""
    return _call_llm(prompt, expect_json=True)


def generate_keyword_narrative(
    keywords: list[dict], app_name: str, use_llm: bool = True
) -> str | None:
    """
    Convert scored keyword data into a plain English strategy paragraph.

    Args:
        keywords: List of keyword dicts with keyword, proxy_opportunity,
                  is_gap_keyword, and rank fields.
        app_name: Name of the target app.
        use_llm:  If False, return None immediately without calling the API.

    Returns:
        Plain text strategy paragraph, or None on failure.
    """
    if not use_llm:
        return None

    top_opportunities = [k for k in keywords if not k.get("is_gap_keyword")]
    gap_keywords = [k for k in keywords if k.get("is_gap_keyword")]

    top_formatted = "\n".join(
        f"- {k['keyword']} (score: {k.get('proxy_opportunity', 0):.3f}, "
        f"rank: {k.get('current_rank', 'unranked')})"
        for k in top_opportunities[:10]
    )
    gap_formatted = "\n".join(
        f"- {k['keyword']} (competitor: {k.get('gap_competitor', 'unknown')})"
        for k in gap_keywords[:5]
    )

    prompt = f"""
You are an ASO (App Store Optimization) expert.

Here is keyword data for {app_name}:

Top opportunity keywords (ranked by score):
{top_formatted}

Gap keywords (competitors rank for these, we do not):
{gap_formatted}

Write a concise 3-4 sentence strategy paragraph that:
1. Identifies the single best keyword opportunity
2. Calls out the most important gap keyword to target
3. Gives one specific actionable recommendation

Write in plain English for a product manager, not a developer.
Do not use bullet points. Return only the paragraph.
"""
    return _call_llm(prompt, expect_json=False)


def compare_competitor_metadata(
    target_app: dict, competitor_app: dict, use_llm: bool = True
) -> dict | None:
    """
    Compare target app description against a competitor's and identify gaps.

    Args:
        target_app:     Dict with name and description fields.
        competitor_app: Dict with name and description fields.
        use_llm:        If False, return None immediately without calling the API.

    Returns:
        Parsed JSON dict with competitor_advantages, target_advantages,
        missing_keywords, and recommendation keys, or None on failure.
    """
    if not use_llm:
        return None

    prompt = f"""
Compare these two App Store descriptions and return a JSON object:
{{
    "competitor_advantages": ["list of messaging points competitor has that target lacks"],
    "target_advantages":     ["list of messaging points target has that competitor lacks"],
    "missing_keywords":      ["important words in competitor description absent from target"],
    "recommendation":        "one specific sentence on what target should add to description"
}}

TARGET APP ({target_app['name']}):
{target_app['description'][:1000]}

COMPETITOR ({competitor_app['name']}):
{competitor_app['description'][:1000]}

Return only the JSON object, no other text.
"""
    return _call_llm(prompt, expect_json=True)


def suggest_description_rewrite(
    current_description: str,
    target_keywords: list[str],
    gaps: list[str],
    use_llm: bool = True,
) -> str | None:
    """
    Generate an optimised rewrite of the app description.

    Args:
        current_description: The app's current App Store description.
        target_keywords:     Top keywords to naturally incorporate.
        gaps:                Gap keywords to add where relevant.
        use_llm:             If False, return None immediately without calling the API.

    Returns:
        Rewritten description string, or None on failure.
    """
    if not use_llm:
        return None

    prompt = f"""
Rewrite this App Store description to naturally incorporate
the target keywords while maintaining a compelling, human tone.

Rules:
- Keep it under 4000 characters (App Store limit)
- Do not keyword stuff — keywords must fit naturally
- Maintain the app's core value proposition
- Lead with the strongest user benefit
- Do not invent features that do not exist

Current description:
{current_description[:2000]}

Keywords to incorporate naturally:
{', '.join(target_keywords[:10])}

Gap keywords to add if relevant:
{', '.join(gaps[:5])}

Return only the rewritten description, no commentary.
"""
    return _call_llm(prompt, expect_json=False)
