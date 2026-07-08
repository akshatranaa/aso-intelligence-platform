# iTunes API endpoints
ITUNES_SEARCH_URL  = "https://itunes.apple.com/search"
ITUNES_LOOKUP_URL  = "https://itunes.apple.com/lookup"
ITUNES_REVIEWS_URL      = "https://itunes.apple.com/{country}/rss/customerreviews/id={app_id}/sortBy=mostRecent/json"
ITUNES_AUTOCOMPLETE_URL = "https://search.itunes.apple.com/WebObjects/MZSearchHints.woa/wa/hints"

# Defaults
DEFAULT_COUNTRY        = "in"
DEFAULT_LIMIT          = 200
RANKING_SEARCH_LIMIT   = 200

# Rate limiting
RATE_LIMIT_SECONDS = 1

# Database — connection string comes from the DATABASE_URL environment variable
# (see database.py). Postgres-hosted (e.g. Neon), not a local file.

# Competitor scoring weights — must sum to 1.0. Relevance is decided by the LLM
# judge (llm_analyst.judge_competitors), so the score only ranks already-relevant
# competitors by popularity and quality for tier assignment.
COMPETITOR_WEIGHTS = {
    "rating_count": 0.70,
    "avg_rating":   0.30,
}

# Competitor tier split. Every LLM-judged competitor is saved; this only decides
# tier1 (top same-category competitors, score >= threshold) vs tier2 (the rest).
TIER_1_THRESHOLD = 0.40

# Competitor candidate discovery — cap the pool the judge has to score:
# up to COMPETITOR_SEEDS_MAX seeds x COMPETITOR_CANDIDATES_PER_SEED results = ~75.
COMPETITOR_SEEDS_MAX          = 5
COMPETITOR_CANDIDATES_PER_SEED = 15

# Re-collecting an app within this many days reuses its already-discovered
# competitors (per country) instead of re-running the searches + LLM judge.
COMPETITOR_REFRESH_DAYS = 7

# Keyword analysis weights — must sum to 1.0
PROXY_OPPORTUNITY_WEIGHTS = {
    "volume":     0.45,
    "relevance":  0.35,
    "difficulty": 0.20
}

# Revised weights when paid Search Ads data is available
REVISED_OPPORTUNITY_WEIGHTS = {
    "confirmed_volume":     0.30,
    "conversion_rate":      0.30,
    "relevance":            0.20,
    "cpi_efficiency":       0.10,
    "confirmed_difficulty": 0.10
}

# Keyword settings
TOP_K_KEYWORDS     = 20
N_REVIEW_CLUSTERS  = 5

# Rank tracking
RANK_ALERT_THRESHOLD = 5
RANK_VELOCITY_DAYS   = 7
# Max competitors to look up in an on-demand per-keyword rank comparison.
RANK_COMPETITOR_COMPARE_MAX = 5

# Logging
LOG_LEVEL  = "INFO"
LOG_FORMAT = "%(asctime)s — %(name)s — %(levelname)s — %(message)s"

# LLM settings — served via Groq (OpenAI-compatible chat completions API).
# Groq's free tier has far higher request/day limits than Gemini's; the small
# 8B model is plenty for this workload (JSON classification + short summaries).
# Bump to "llama-3.3-70b-versatile" for better quality at a lower daily cap.
GROQ_BASE_URL         = "https://api.groq.com/openai/v1/chat/completions"
LLM_MODEL             = "llama-3.1-8b-instant"
# The competitor judge is accuracy-critical (one call/collect) — use a stronger
# model so it reliably excludes junk without dropping real competitors.
JUDGE_LLM_MODEL       = "llama-3.3-70b-versatile"
LLM_MAX_TOKENS        = 1024  # per-call output cap (conserves free quota)
LLM_MAX_RETRIES       = 2     # retries on transient errors (429/503/timeout)
LLM_REVIEW_BATCH_SIZE = 20
LLM_TOP_REVIEWS       = 30    # trimmed to conserve free quota

# Sentiment thresholds (VADER compound score)
SENTIMENT_POSITIVE_THRESHOLD =  0.05
SENTIMENT_NEGATIVE_THRESHOLD = -0.05

# Keyword extraction
MIN_KEYWORD_LENGTH   = 3
MAX_NGRAM_SIZE       = 3
MIN_TFIDF_SCORE      = 0.01
TOP_K_TFIDF_KEYWORDS = 100

# Rank tracking (Week 2)
MIN_DAYS_FOR_VELOCITY = 3

# Search Ads scoring
MAX_CPI              = 5.0    # CPIs above this are treated as maximum difficulty
SEARCH_ADS_BASE_URL  = "https://api.searchads.apple.com/api/v4"
SEARCH_ADS_TOKEN_URL = "https://appleid.apple.com/auth/oauth2/token"
SEARCH_ADS_LOOKBACK_DAYS = 90
