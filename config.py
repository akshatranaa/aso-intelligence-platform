# iTunes API endpoints
ITUNES_SEARCH_URL  = "https://itunes.apple.com/search"
ITUNES_LOOKUP_URL  = "https://itunes.apple.com/lookup"
ITUNES_REVIEWS_URL      = "https://itunes.apple.com/{country}/rss/customerreviews/id={app_id}/sortBy=mostRecent/json"
ITUNES_AUTOCOMPLETE_URL = "https://search.itunes.apple.com/WebObjects/MZSearchHints.woa/wa/hints"

# Defaults
DEFAULT_COUNTRY        = "us"
DEFAULT_LIMIT          = 200
RANKING_SEARCH_LIMIT   = 200

# Rate limiting
RATE_LIMIT_SECONDS = 1

# Database
DATABASE_PATH = "aso_data.db"

# Competitor scoring weights — must sum to 1.0
COMPETITOR_WEIGHTS = {
    "rating_count":    0.35,
    "avg_rating":      0.15,
    "keyword_overlap": 0.40,
    "category_match":  0.10
}

# Competitor tier thresholds
TIER_1_THRESHOLD = 0.75
TIER_2_THRESHOLD = 0.45

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

# Logging
LOG_LEVEL  = "INFO"
LOG_FORMAT = "%(asctime)s — %(name)s — %(levelname)s — %(message)s"

# LLM settings
LLM_MODEL             = "claude-sonnet-4-6"
LLM_MAX_TOKENS        = 1024
LLM_REVIEW_BATCH_SIZE = 20
LLM_TOP_REVIEWS       = 50

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
