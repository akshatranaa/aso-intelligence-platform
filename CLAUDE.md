# ASO Intelligence Platform — CLAUDE.md
# Single source of truth for the entire project.
# Read this file completely before writing any code.
# Every decision here was made deliberately. Do not deviate.

---

## What this project is

An App Store Optimization (ASO) intelligence platform that:
1. Collects app metadata, reviews, and keyword rankings from Apple's free public APIs
2. Discovers and scores competitor apps using scored BFS
3. Runs keyword analysis, sentiment analysis, and rank tracking
4. Surfaces actionable recommendations for improving App Store visibility

---

## Folder structure — do not change this

```
aso_platform/
├── main.py                      # orchestration only, no business logic
├── config.py                    # ALL constants live here, nowhere else
├── database.py                  # ALL database operations live here
├── requirements.txt             # no new libraries without updating this
├── .env                         # API credentials, never commit this file
├── .gitignore                   # must include .env and aso_data.db
│

├── collection/
│   ├── scraper.py               # ALL iTunes API HTTP calls live here
│   ├── competitor.py            # scored BFS competitor discovery
│   └── scheduler.py            # daily collection job scheduling
│
├── analysis/
│   ├── llm_analyst.py           # ALL Anthropic API calls live here
│   ├── keyword_analysis.py      # autocomplete discovery, scoring, gap analysis
│   ├── sentiment.py             # LLM-first sentiment, VADER fallback
│   ├── rank_tracker.py          # snapshots, deltas, velocity
│   └── recommendations.py      # decision engine, field suggestions
│
├── search_ads/
│   ├── auth.py                  # Apple OAuth 2.0 only
│   ├── fetcher.py               # Search Ads API data fetching
│   └── scheduler.py            # daily Search Ads fetch scheduling
│
└── api/
    └── main.py                  # FastAPI server, all endpoints
```

---

## config.py — complete contents

```python
# iTunes API endpoints
ITUNES_SEARCH_URL      = "https://itunes.apple.com/search"
ITUNES_LOOKUP_URL      = "https://itunes.apple.com/lookup"
ITUNES_REVIEWS_URL     = "https://itunes.apple.com/{country}/rss/customerreviews/id={app_id}/sortBy=mostRecent/json"
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
TOP_K_KEYWORDS        = 20
MIN_KEYWORD_LENGTH    = 3
MAX_NGRAM_SIZE        = 3
MIN_TFIDF_SCORE       = 0.01
TOP_K_TFIDF_KEYWORDS  = 100
N_REVIEW_CLUSTERS     = 5

# Rank tracking
RANK_ALERT_THRESHOLD  = 5
RANK_VELOCITY_DAYS    = 7
MIN_DAYS_FOR_VELOCITY = 3

# LLM settings
LLM_MODEL              = "claude-sonnet-4-6"
LLM_MAX_TOKENS         = 1024
LLM_REVIEW_BATCH_SIZE  = 20
LLM_TOP_REVIEWS        = 50

# Sentiment thresholds (VADER compound score — fallback only)
SENTIMENT_POSITIVE_THRESHOLD =  0.05
SENTIMENT_NEGATIVE_THRESHOLD = -0.05

# Logging
LOG_LEVEL  = "INFO"
LOG_FORMAT = "%(asctime)s — %(name)s — %(levelname)s — %(message)s"
```

---

## Database

### Engine
- SQLite for development
- Use Python's built-in sqlite3 module directly
- All table definitions and queries live in database.py
- No SQL anywhere else in the codebase

### Connection pattern
```python
import sqlite3
from contextlib import contextmanager
import config

@contextmanager
def get_connection():
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
```

### Table 1: apps
```sql
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
);
```

### Table 2: reviews
```sql
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
);
```

### Table 3: keywords
```sql
CREATE TABLE IF NOT EXISTS keywords (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    app_id               INTEGER NOT NULL,
    keyword              TEXT NOT NULL,
    proxy_volume         REAL,
    proxy_difficulty     REAL,
    proxy_opportunity    REAL,
    confirmed_volume     REAL,
    confirmed_conversion REAL,
    confirmed_cpi        REAL,
    revised_opportunity  REAL,
    keyword_bucket       TEXT,
    is_hidden_gem        INTEGER DEFAULT 0,
    is_gap_keyword       INTEGER DEFAULT 0,
    gap_competitor       TEXT,
    source               TEXT,
    created_at           TEXT NOT NULL,
    updated_at           TEXT NOT NULL,
    FOREIGN KEY (app_id) REFERENCES apps(app_id)
);
```

### Table 4: rankings
```sql
CREATE TABLE IF NOT EXISTS rankings (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    app_id              INTEGER NOT NULL,
    keyword             TEXT NOT NULL,
    rank                INTEGER,
    date                TEXT NOT NULL,
    rank_delta          INTEGER,
    rank_velocity       REAL,
    FOREIGN KEY (app_id) REFERENCES apps(app_id)
);
```

### Table 5: search_ads_campaigns
```sql
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
);
```

### Table 6: search_ads_keyword_data
```sql
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
);
```

### Required functions in database.py

```
Week 1 functions (already built):
  create_tables()
  save_app(app_dict)
  save_reviews(reviews_list)
  save_ranking(app_id, keyword, rank, date)
  get_app(app_id)
  get_all_apps()
  get_reviews(app_id)
  get_rankings(app_id, keyword)
  app_exists(app_id)
  get_yesterday_rank(app_id, keyword)

Week 2 additions:
  get_keywords(app_id) -> list[dict]
      SELECT * FROM keywords WHERE app_id = ?

  save_keyword(keyword_dict) -> None
      INSERT OR REPLACE INTO keywords (...) VALUES (:col, ...)
      Use named :param style, pass full dict directly

  update_sentiment(review_id, score, label) -> None
      UPDATE reviews SET sentiment_score=?, sentiment_label=?
      WHERE review_id=?

  get_competitor_apps() -> list[dict]
      SELECT * FROM apps WHERE is_target_app = 0

  get_target_app() -> dict | None
      SELECT * FROM apps WHERE is_target_app = 1 LIMIT 1

  get_all_rankings(app_id) -> list[dict]
      SELECT * FROM rankings WHERE app_id = ?
      ORDER BY date ASC
```

---

## collection/scraper.py

### Responsibility
Only file allowed to make HTTP requests to Apple's free APIs.
No database calls. No analysis. Only fetch and return data.

### HTTP client
```python
import httpx
client = httpx.Client(timeout=30.0)
```

### Rate limiting — call after EVERY API request, no exceptions
```python
def _rate_limit():
    time.sleep(config.RATE_LIMIT_SECONDS)
```

### Error handling pattern — use in every function
```python
try:
    response = client.get(url, params=params)
    response.raise_for_status()
    data = response.json()
    # process and return
except httpx.TimeoutException:
    logger.error(f"Timeout: {url}")
    return None  # or [] for list-returning functions
except httpx.HTTPStatusError as e:
    logger.error(f"HTTP {e.response.status_code}: {url}")
    return None
except Exception as e:
    logger.error(f"Unexpected error {url}: {e}")
    return None
finally:
    _rate_limit()
```

### Required functions

#### fetch_app_metadata(app_name, country) -> dict | None
```
Search iTunes by name. Returns app metadata dict or None.
API: GET ITUNES_SEARCH_URL, params: term, entity=software, country, limit=1
Field mapping: trackId→app_id, trackName→name, primaryGenreName→category,
  averageUserRating→avg_rating, userRatingCount→rating_count,
  sellerName→seller_name, bundleId→bundle_id, minimumOsVersion→min_os_version
```

#### fetch_app_by_id(app_id, country) -> dict | None
```
Fetch exact app by numeric ID. Same return structure as fetch_app_metadata.
API: GET ITUNES_LOOKUP_URL, params: id=app_id, country
Use this everywhere after initial name lookup.
```

#### fetch_reviews(app_id, country) -> list[dict]
```
Fetch most recent reviews from iTunes RSS feed.
API: GET ITUNES_REVIEWS_URL formatted with country and app_id
Skip first entry (it describes the app, not a review).
Returns list of {review_text, rating, review_date, author}
Returns [] on any failure — never None.
```

#### fetch_keyword_ranking(keyword, target_app_id, country) -> int | None
```
Find position of target app in search results for keyword.
API: GET ITUNES_SEARCH_URL, params: term=keyword, entity=software,
     country, limit=config.RANKING_SEARCH_LIMIT
Iterate results with enumerate, find trackId==target_app_id.
Return index+1 (1-indexed). Return None if not found.
```

#### fetch_keyword_apps(keyword, country, limit=20) -> list[int]
```
Return list of app_ids from top results for a keyword.
Used by competitor BFS for neighbour discovery.
Returns [] on failure.
```

#### fetch_keyword_suggestions(term, country) -> list[str]
```
Fetch App Store autocomplete suggestions for a search term.
These are REAL keywords users actually type — primary keyword source.
API: GET ITUNES_AUTOCOMPLETE_URL
params: q=term, media=software, country=country
Returns list of suggestion strings.
Returns [] on any failure.
```

---

## collection/competitor.py

### Responsibility
Discover and score competitor apps using scored BFS.
Uses scraper.py for API calls.
Uses database.py to save discovered apps.

### Required functions

#### calculate_competitor_score(app_data, target_keywords, target_category) -> float
```
Weights from config.COMPETITOR_WEIGHTS:
  rating_count_score = min(rating_count / 1_000_000, 1.0)
  avg_rating_score   = (avg_rating - 1) / 4
  category_match     = 1.0 if same category else 0.0
  keyword_overlap    = _compute_keyword_overlap(app_id, target_keywords)

score = sum of weighted signals, rounded to 4 decimal places
```

#### assign_tier(score) -> str | None
```
score >= TIER_1_THRESHOLD (0.75) → "tier1"
score >= TIER_2_THRESHOLD (0.45) → "tier2"
below                            → None
```

#### discover_competitors(target_app_id, target_keywords, max_depth=1) -> list[dict]
```
Scored BFS from target app.
Only explore neighbours of apps scoring above tier2 threshold.
Save qualifying apps to database with competitor_score and competitor_tier.
Return sorted by score descending.
Default max_depth=1 for reasonable run time.
```

---

## analysis/llm_analyst.py

### Responsibility
Single file owning ALL Anthropic API calls.
No other file calls the Anthropic API directly.
Every function has use_llm=True parameter.
use_llm=False returns None immediately — no API call made.

### Client setup
```python
from dotenv import load_dotenv
import anthropic
load_dotenv()
client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from .env
```

### Helper: _call_llm(prompt, expect_json=False)
```
All four public functions route through this.
Strips markdown code fences before JSON parsing.
Returns None on any failure — never raises.
```

### Required functions

#### analyse_reviews(reviews, use_llm=True) -> dict | None
```
Sends up to LLM_TOP_REVIEWS reviews as numbered list.
Format: "1. [5 stars] review text\n2. [3 stars] ..."
Returns JSON: {top_complaints, top_praise, overall_sentiment,
               priority_fix, sentiment_summary}
expect_json=True
```

#### generate_keyword_narrative(keywords, app_name, use_llm=True) -> str | None
```
Splits keywords into top_opportunities and gap_keywords.
Sends formatted lists to LLM.
Returns 3-4 sentence plain English strategy paragraph.
expect_json=False
```

#### compare_competitor_metadata(target_app, competitor_app, use_llm=True) -> dict | None
```
Sends first 1000 chars of each description.
Returns JSON: {competitor_advantages, target_advantages,
               missing_keywords, recommendation}
expect_json=True
```

#### suggest_description_rewrite(current_description, target_keywords, gaps, use_llm=True) -> str | None
```
Sends current description + keywords to incorporate.
Rules: under 4000 chars, no keyword stuffing, no invented features.
Returns rewritten description string.
expect_json=False
```

---

## analysis/sentiment.py

### Responsibility
Score reviews for one app using LLM as primary method.
VADER is fallback only when use_llm=False.
Never makes HTTP calls to Apple.
Writes results back to reviews table.

### Key design decisions
- LLM is primary scorer (understands sarcasm, context, Hinglish)
- VADER is fallback for when use_llm=False (no API credits)
- sentiment_score is None for LLM path (no numeric score from LLM)
- sentiment_label is always populated regardless of path
- LLM is only called for ambiguous 3-star reviews (cost optimisation)
- 4 and 5 star reviews → positive directly (no LLM needed)
- 1 and 2 star reviews → negative directly (no LLM needed)
- 3 star reviews → sent to LLM in batches for disambiguation

### Required functions

#### score_all_reviews(app_id, use_llm=True) -> dict
```
Master function.
Routes to _score_with_llm or _score_with_vader based on use_llm.
Calls _save_sentiment_labels and _build_summary.
Returns aggregate summary dict with app_id.
```

#### _score_with_llm(reviews) -> list[dict]
```
Step 1: separate obvious from ambiguous
  obvious   = reviews where rating != 3
  ambiguous = reviews where rating == 3

Step 2: label obvious reviews directly — no LLM
  rating >= 4 → positive
  rating <= 2 → negative

Step 3: batch ambiguous reviews only
  batches of LLM_REVIEW_BATCH_SIZE
  call llm_analyst.analyse_reviews(batch)
  use _infer_label_from_llm for each review in batch
  fallback to _label_from_rating if LLM call fails

All reviews get sentiment_score=None, sentiment_label=label
```

#### _infer_label_from_llm(text, rating, llm_result, overall) -> str
```
rating >= 4 → positive
rating <= 2 → negative
rating == 3 and overall == "positive" → positive
rating == 3 and overall == "negative" → negative
rating == 3 otherwise → neutral
```

#### _label_from_rating(rating) -> str
```
Fallback when LLM fails entirely.
rating >= 4 → positive
rating <= 2 → negative
else → neutral
```

#### _score_with_vader(reviews) -> list[dict]
```
VADER fallback path.
Uses SentimentIntensityAnalyzer at module level.
Adds sentiment_score (compound) and sentiment_label to each review.
```

#### _label_from_score(compound) -> str
```
Used by VADER path only.
compound >= SENTIMENT_POSITIVE_THRESHOLD → positive
compound <= SENTIMENT_NEGATIVE_THRESHOLD → negative
else → neutral
```

#### _save_sentiment_labels(reviews) -> None
```
Use conn.executemany() for efficiency.
UPDATE reviews SET sentiment_score=?, sentiment_label=?
WHERE review_id=?
```

#### _build_summary(reviews) -> dict
```
Returns: total_reviews, positive/negative/neutral counts and pcts,
         avg_rating (rounded to 2dp), percentages rounded to 1dp
```

#### _empty_summary(app_id) -> dict
```
Returns zero-value summary when no reviews exist.
Prevents division by zero.
```

#### get_sentiment_summary(app_id) -> dict | None
```
Reads already-scored reviews from database.
Does NOT recompute. For API layer use in Week 4.
Filters: only reviews where sentiment_label is not None.
```

---

## analysis/keyword_analysis.py

### Responsibility
Discover keywords using Apple's autocomplete API (real search data).
Score each keyword for volume, difficulty, opportunity.
Find gaps vs competitors.
Write results to keywords table.
Makes iTunes API calls to score keywords.

### Key design decision
TF-IDF is NOT used for keyword discovery.
Apple's autocomplete API returns real user search terms — always superior
to inferring keywords from descriptions. If users do not type a term in
the App Store search bar, it is not worth targeting regardless.

### Required functions

#### run_keyword_analysis(app_id, use_llm=True) -> dict
```
Master function. Runs full pipeline:
1. target_app = database.get_app(app_id)
2. all_apps   = database.get_all_apps()
3. candidates = extract_keywords(target_app, all_apps)
4. scored     = score_keywords(candidates, app_id)
5. gaps       = find_keyword_gaps(app_id)
6. _save_keywords(scored + gaps, app_id)
7. top_k      = get_top_k_keywords(app_id)
8. narrative  = llm_analyst.generate_keyword_narrative(top_k+gaps, name)
9. return {top_keywords, gaps, narrative}
```

#### extract_keywords(target_app, all_apps) -> list[str]
```
Three sources, all using Apple's autocomplete API:

Source 1: seed term expansion
  Seeds: app name, category, "music player", "music streaming", "podcast app"
  For each seed: fetch_keyword_suggestions(seed)

Source 2: alphabet expansion on app name
  base = first word of app name (e.g. "spotify")
  For each letter a-z: fetch_keyword_suggestions(f"{base} {letter}")
  Surfaces long-tail keywords

Source 3: competitor name expansion
  Only tier1 competitors, max 5
  For each: fetch_keyword_suggestions(competitor_first_name)

Combine all results in a set (auto-deduplication).
Return as list.
```

#### score_keywords(keywords, app_id) -> list[dict]
```
For each keyword — makes 2 iTunes API calls:
  top_ids    = scraper.fetch_keyword_apps(keyword, limit=10)
  top_apps   = _fetch_apps(top_ids)  ← DB first, API fallback
  volume     = _estimate_volume(top_apps)
  difficulty = _estimate_difficulty(top_apps)
  rank       = scraper.fetch_keyword_ranking(keyword, app_id)
  relevance  = _tfidf_relevance(keyword, top_apps)
  opportunity = _calculate_opportunity(volume, difficulty, relevance)

Returns list of scored dicts with:
  keyword, proxy_volume, proxy_difficulty, proxy_opportunity,
  current_rank, source="autocomplete", is_gap_keyword=0
```

#### _fetch_apps(app_ids) -> list[dict]
```
For each app_id: database.get_app(app_id) or scraper.fetch_app_by_id(app_id)
DB-first pattern — avoids unnecessary API calls for already-known apps.
```

#### _tfidf_relevance(keyword, top_apps) -> float
```
Fraction of top_apps whose description contains the keyword.
Simple string match, case-insensitive.
Returns 0.0 if no top_apps.
```

#### _estimate_volume(top_apps) -> float
```
avg_rating_count = mean of rating_count across top_apps
return min(avg_rating_count / 5_000_000, 1.0)
```

#### _estimate_difficulty(top_apps) -> float
```
For each app at position i (1-indexed, max 10):
  position_weight = (11 - i) / 10
  app_strength    = min(rating_count / 2_000_000, 1.0) * (avg_rating / 5.0)
  weighted_score += app_strength * position_weight
return min(weighted_score / 5.0, 1.0)
```

#### _calculate_opportunity(volume, difficulty, relevance) -> float
```
weights = config.PROXY_OPPORTUNITY_WEIGHTS
score = (volume * 0.45) + (relevance * 0.35) - (difficulty * 0.20)
return max(0.0, min(1.0, score))
```

#### find_keyword_gaps(app_id) -> list[dict]
```
target_keywords = set of keywords from database.get_all_rankings(app_id)
For each competitor in database.get_competitor_apps():
  comp_keywords = set from database.get_all_rankings(comp_id)
  gaps = comp_keywords - target_keywords
  score each gap keyword
  deduplicate keeping highest opportunity score
Return sorted by opportunity descending.
Each gap dict has is_gap_keyword=1, gap_competitor=name.
```

#### get_top_k_keywords(app_id, k=config.TOP_K_KEYWORDS) -> list[dict]
```
Use max-heap (heapq) for efficiency.
heap = [(-kw["proxy_opportunity"], kw) for kw in all_keywords]
heapq.heapify(heap)
pop k times, return list of kw dicts.
```

#### _save_keywords(keywords, app_id) -> None
```
Build complete dict matching all keywords table columns.
confirmed_* fields all None (populated in Week 3 via Search Ads).
Use database.save_keyword() for each.
One timestamp for all keywords in this run.
```

---

## analysis/rank_tracker.py

### Responsibility
Take daily ranking snapshots.
Compute rank delta and velocity from history.
Detect significant changes.
No LLM. No iTunes API calls except via scraper.

### Required functions

#### take_snapshot(app_id, keywords) -> dict
```
today = str(date.today())
For each keyword:
  rank = scraper.fetch_keyword_ranking(keyword, app_id)
  if rank: database.save_ranking(app_id, keyword, rank, today)
Returns dict mapping keyword → rank
```

#### compute_velocity(app_id, keyword) -> float | None
```
rows = database.get_rankings(app_id, keyword) ordered by date ASC
if len(rows) < MIN_DAYS_FOR_VELOCITY: return None
recent = last RANK_VELOCITY_DAYS rows
deltas = [rows[i]["rank"] - rows[i-1]["rank"] for i in range(1, len(recent))]
velocity = mean of deltas
  negative = climbing (rank number decreasing = good)
  positive = dropping (rank number increasing = bad)
UPDATE rankings SET rank_velocity=velocity for most recent row.
return velocity
```

#### compute_all_velocities(app_id) -> dict
```
Run compute_velocity for every keyword tracked for this app.
Returns dict: keyword → velocity
```

#### detect_significant_changes(app_id, keywords) -> list[dict]
```
For each keyword: get most recent ranking row
If abs(rank_delta) > RANK_ALERT_THRESHOLD:
  append {keyword, old_rank, new_rank, delta,
          direction: "up"|"down", velocity}
```

#### get_ranking_summary(app_id) -> list[dict]
```
For each tracked keyword return:
  {keyword, rank, delta, velocity,
   trend: "improving"|"declining"|"stable"|"unknown"}

trend logic:
  velocity is None       → "unknown"
  velocity < -0.5        → "improving"
  velocity > 0.5         → "declining"
  else                   → "stable"
```

---

## main.py — complete orchestration

```
Step 1:  configure logging
Step 2:  read target app name from sys.argv[1]
Step 3:  database.create_tables()
Step 4:  fetch and save target app (is_target_app=1)
Step 5:  define seed keywords (5 hardcoded)
Step 6:  competitor.discover_competitors(max_depth=1)
Step 7:  record keyword rankings for 5 seed keywords
Step 8:  fetch and save reviews for target app
Step 9:  log completion summary (apps, reviews, rankings)
Step 10: sentiment.score_all_reviews(target_app_id, use_llm=False)
Step 11: keyword_analysis.run_keyword_analysis(target_app_id, use_llm=False)
Step 12: rank_tracker.take_snapshot + compute_all_velocities + detect_significant_changes
```

Run with: python3 main.py "Spotify"
Change use_llm=False to use_llm=True once API credits are available.

---

## Coding standards — enforced on every file

### Compatibility
Add to top of every file:
  from __future__ import annotations
Required for Python 3.9 compatibility with union type hints (dict | None).

### Docstrings — every function
```python
def function_name(param: type) -> return_type:
    """
    One line summary.

    Args:
        param: description

    Returns:
        description
    """
```

### Type hints — every function signature
```python
def save_reviews(reviews: list[dict]) -> int:
def get_app(app_id: int) -> dict | None:
def app_exists(app_id: int) -> bool:
```

### Logging — never use print()
```python
logger = logging.getLogger(__name__)  # module level, every file
logger.info("normal operations")
logger.warning("non-fatal issues")
logger.error("failures")
```

### Parameterised SQL — never string formatting
```python
# CORRECT
cursor.execute("SELECT * FROM apps WHERE app_id = ?", (app_id,))
# WRONG — never do this
cursor.execute(f"SELECT * FROM apps WHERE app_id = {app_id}")
```

### No magic numbers
```python
# CORRECT
time.sleep(config.RATE_LIMIT_SECONDS)
# WRONG
time.sleep(1)
```

### No function longer than 40 lines
### Module-level logger in every file
### No hardcoded values outside config.py

---

## Build order for Claude Code

Build one module at a time. Do not proceed until instructed.

Week 1 (complete):
  1. config.py               ✓
  2. database.py             ✓
  3. collection/scraper.py   ✓
  4. collection/competitor.py ✓
  5. main.py                 ✓

Week 2 (in progress):
  6.  database.py additions  ✓ (5 new functions)
  7.  analysis/llm_analyst.py ✓
  8.  analysis/sentiment.py  ✓ (LLM-first version)
  9.  analysis/keyword_analysis.py ✓
  9b. scraper.py addition    → add fetch_keyword_suggestions()
  9c. database.py addition   → add get_all_rankings()
  10. analysis/rank_tracker.py → NEXT TO BUILD
  11. update main.py         → add steps 10, 11, 12

Week 3 (upcoming):
  12. search_ads/auth.py
  13. search_ads/fetcher.py
  14. analysis/recommendations.py

Week 4 (upcoming):
  15. api/main.py (FastAPI)
  16. dashboard (Streamlit first)

---

## Verification after full Week 2 run

```bash
python3 main.py "Spotify"
```

Database checks:
```sql
SELECT sentiment_label, COUNT(*) FROM reviews GROUP BY sentiment_label;
SELECT keyword, proxy_opportunity, is_gap_keyword
FROM keywords ORDER BY proxy_opportunity DESC LIMIT 10;
SELECT keyword, rank, rank_delta, rank_velocity
FROM rankings ORDER BY date DESC;
```

Expected terminal output includes:
  INFO — Sentiment: XX% positive, XX% negative
  INFO — Keywords: XX scored, XX gaps found
  INFO — Rankings recorded with velocity

---

## Requirements.txt

```
httpx==0.27.0
nltk==3.8.1
scikit-learn==1.4.2
sentence-transformers==2.7.0
vaderSentiment==3.3.2
apscheduler==3.10.4
fastapi==0.111.0
uvicorn==0.29.0
pydantic==2.7.1
PyJWT==2.8.0
pandas==2.2.2
numpy==1.26.4
python-dotenv==1.0.1
anthropic>=0.25.0
```
