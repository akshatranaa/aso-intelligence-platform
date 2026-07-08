"""Owns all LLM API calls (via Groq). No other module calls the API directly."""

from __future__ import annotations

import json
import logging
import os
import time

import httpx
from dotenv import load_dotenv

import config

load_dotenv()

logger = logging.getLogger(__name__)

# Provider-side transient statuses worth retrying.
_RETRYABLE_STATUS = {429, 500, 502, 503, 529}


def _call_llm(
    prompt: str, expect_json: bool = False, model: str | None = None
) -> dict | list | str | None:
    """
    Central function that makes every LLM API call, via Groq.

    Uses Groq's OpenAI-compatible chat-completions endpoint. Retries up to
    config.LLM_MAX_RETRIES times on transient errors (rate limits, upstream
    unavailability, timeouts) with exponential backoff. Non-transient failures
    (bad key, bad request, JSON parse) are not retried.

    Args:
        prompt:      Full prompt string to send.
        expect_json: If True, parse the response text as JSON before returning.
        model:       Groq model override (defaults to config.LLM_MODEL).

    Returns:
        Parsed JSON dict/list if expect_json=True, raw string otherwise,
        or None if the call ultimately fails or the JSON parse fails.
    """
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        logger.error("GROQ_API_KEY not set — skipping LLM call")
        return None

    model = model or config.LLM_MODEL
    url = config.GROQ_BASE_URL
    text = None
    for attempt in range(config.LLM_MAX_RETRIES + 1):
        try:
            response = httpx.post(
                url,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": config.LLM_MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": config.LLM_MAX_TOKENS,
                    "temperature": 0,
                },
                timeout=60.0,
            )
            if response.status_code in _RETRYABLE_STATUS and attempt < config.LLM_MAX_RETRIES:
                wait = 2 ** attempt
                logger.warning(
                    f"LLM {response.status_code} "
                    f"(attempt {attempt + 1}/{config.LLM_MAX_RETRIES + 1}), retrying in {wait}s"
                )
                time.sleep(wait)
                continue
            response.raise_for_status()
            choices = response.json().get("choices", [])
            text = choices[0].get("message", {}).get("content") if choices else None
            break
        except httpx.RequestError as e:
            # Network/timeout error — retry if attempts remain, else give up.
            if attempt < config.LLM_MAX_RETRIES:
                wait = 2 ** attempt
                logger.warning(f"LLM network error (attempt {attempt + 1}), retrying in {wait}s: {e}")
                time.sleep(wait)
                continue
            logger.error(f"LLM API call failed: {e}")
            return None
        except Exception as e:
            logger.error(f"LLM API call failed: {e}")
            return None

    if text is None:
        return None

    if not expect_json:
        return text
    try:
        text = text.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        return json.loads(text.strip())
    except Exception as e:
        logger.error(f"LLM JSON parse failed: {e}")
        return None


def generate_seed_keywords(app_data: dict, use_llm: bool = True) -> list[str] | None:
    """
    Generate app-specific seed search terms from the app's name and description.

    These are the terms real users would type to find apps like this one —
    far more targeted than the generic category-based fallback (e.g. "vpn",
    "secure vpn", "wifi proxy" for a VPN app instead of "productivity").

    Args:
        app_data: App metadata dict with name, category, and description.
        use_llm:  If False, return None immediately without calling the API.

    Returns:
        List of lowercase seed term strings, or None on failure/opt-out.
    """
    if not use_llm:
        return None

    name        = app_data.get("name", "")
    category    = app_data.get("category", "")
    description = (app_data.get("description") or "")[:500]

    prompt = f"""
You are an App Store Optimization expert.

Give 5-8 short seed search terms (1-3 words each) that real users would type
into the App Store to discover apps like this one. Focus on the app's core
function and category — not its brand name.

App name: {name}
Category: {category}
Description: {description}

Return ONLY a JSON array of lowercase strings and nothing else.
Example: ["vpn", "secure vpn", "wifi proxy", "unblock sites"]
"""
    result = _call_llm(prompt, expect_json=True)
    if not isinstance(result, list):
        return None
    seeds = [str(s).strip().lower() for s in result if str(s).strip()]
    return seeds or None


def judge_competitors(
    target_app: dict, candidates: list[dict], use_llm: bool = True
) -> set[int] | None:
    """
    Classify which candidate apps are genuine competitors of the target.

    One batched LLM call reads the target and each candidate (name + short
    description) and returns the app_ids that share the target's core purpose —
    so unrelated-but-popular apps (ChatGPT, Calculator) are excluded regardless
    of category or keyword overlap.

    Args:
        target_app: Target app dict with name and description.
        candidates: List of candidate app dicts (app_id, name, description).
        use_llm:    If False, return all candidate ids (no gating).

    Returns:
        Set of competitor app_ids on success (possibly empty). Returns None when
        the LLM call fails (e.g. quota exhausted) so the caller can surface an
        error instead of saving an ungated junk list.
    """
    all_ids = {c["app_id"] for c in candidates}
    if not candidates:
        return set()
    if not use_llm:
        return all_ids

    def _short(app):
        return (app.get("description") or "")[:120].replace("\n", " ")

    # Name + category only — truncated descriptions add noise and make the judge
    # erratic (it dropped obvious VPNs). The app name is the cleanest signal.
    listing = "\n".join(
        f'{c["app_id"]}: {c.get("name","")} [{c.get("category","")}]'
        for c in candidates
    )
    prompt = f"""
You are a strict App Store competitive-analysis expert. Identify ONLY genuine
direct competitors — apps that serve the SAME primary purpose as the target, that
a user would realistically use INSTEAD of it for the same core need.

TARGET APP: {target_app.get("name","")} [{target_app.get("category","")}] — {_short(target_app)}

INCLUDE a candidate when its PRIMARY function is essentially the same as the
target's core function. Judge by what the app actually DOES, not its store
category — apps are often mis-categorised (e.g. VPNs are commonly listed under
"Productivity"). If the target is a VPN, every genuine VPN/proxy app is a
competitor; if it's a music player, every music-streaming app is; and so on.

EXCLUDE a candidate when its main purpose is clearly something else — even if it is
popular, shares a keyword, sits in the same store category, or bundles a minor
related feature. Common things to exclude for most targets: general-purpose AI
assistants / chatbots (e.g. ChatGPT, Perplexity), note-taking / to-do / calendar /
habit / focus / screen-time apps, web browsers, and other tools whose core job
differs from the target's. Popularity is never a reason to include.

Candidates (format "app_id: name [category]"):
{listing}

Return ONLY a JSON array of the app_id integers that qualify — no explanation, no
markdown, no text outside the array. If none qualify, return [].
"""
    result = _call_llm(prompt, expect_json=True, model=config.JUDGE_LLM_MODEL)
    if not isinstance(result, list):
        logger.warning("Competitor judge LLM call failed — signalling error")
        return None
    judged = set()
    for x in result:
        try:
            judged.add(int(x))
        except (TypeError, ValueError):
            continue
    # Only trust ids that were actually in the candidate set.
    return judged & all_ids


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
