"""Seed search-term derivation shared by competitor discovery and rank tracking."""

from __future__ import annotations

import logging
import string

from analysis import llm_analyst

logger = logging.getLogger(__name__)


def derive_seed_keywords(app_data: dict, use_llm: bool = False) -> tuple[list[str], bool]:
    """
    Build seed search terms for a target app.

    With use_llm=True, asks the LLM for targeted, function-based seeds
    (e.g. "vpn", "secure vpn" for a VPN app) and combines them with the
    app name. Falls back to name + category when the LLM is off or fails.
    Shared by competitor discovery and rank tracking.

    Args:
        app_data: App metadata dict with at least 'name' and 'category'.
        use_llm:  Whether to generate seeds via the LLM.

    Returns:
        Tuple of (deduplicated lowercase seed terms, used_llm_seeds). The flag
        is True only when the LLM actually produced seeds; False when use_llm
        is off or the LLM failed and it fell back to category seeds.
    """
    name = app_data.get("name", "").split(":")[0].strip(string.punctuation).strip().lower()

    if use_llm:
        llm_seeds = llm_analyst.generate_seed_keywords(app_data, use_llm=True)
        if llm_seeds:
            seeds = ([name] if name else []) + llm_seeds
            return [s for s in dict.fromkeys(seeds) if s], True

    # Fallback: name + category-based seeds
    category = (app_data.get("category") or "").strip().lower()
    seeds = []
    if name:
        seeds.append(name)
    if category:
        seeds.append(category)
        seeds.append(f"{category} app")
    return [s for s in dict.fromkeys(seeds) if s], False
