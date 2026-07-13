/** Shapes returned by the FastAPI backend (see api/main.py). */

export interface AppSummary {
  app_id: number;
  name: string;
  category: string | null;
  countries: string[];
}

export interface AppSearchResult {
  app_id: number;
  name: string;
  category: string | null;
  seller: string | null;
  artwork: string | null;
}

export interface AppDetail {
  app_id: number;
  name: string;
  description: string | null;
  category: string | null;
  avg_rating: number | null;
  rating_count: number | null;
  price: number | null;
  seller_name: string | null;
  min_os_version: string | null;
  version: string | null;
  country: string | null;
  countries: string[];
}

export interface SentimentSummary {
  app_id: number;
  total_reviews: number;
  positive_count: number;
  negative_count: number;
  neutral_count: number;
  positive_pct: number;
  negative_pct: number;
  neutral_pct: number;
  avg_rating: number;
  /** Official App Store average — all ratings incl. silent star-only taps. */
  store_avg_rating: number | null;
  store_rating_count: number | null;
}

export interface Review {
  review_id: number;
  rating: number | null;
  sentiment_label: string | null;
  review_text: string | null;
  author: string | null;
  review_date: string | null;
}

export interface RankingRow {
  keyword: string;
  rank: number | null;
  delta: number | null;
  velocity: number | null;
  trend: "improving" | "declining" | "stable" | "unknown";
}

export interface CompareResult {
  keyword: string;
  target: { name: string; rank: number | null };
  competitors: { name: string; app_id: number; rank: number | null }[];
}

export interface Competitor {
  app_id: number;
  name: string;
  category: string | null;
  seller_name: string | null;
  avg_rating: number | null;
  rating_count: number | null;
  competitor_score: number | null;
  competitor_tier: "tier1" | "tier2";
}

export interface PriorityAction {
  priority: "high" | "medium" | "low";
  area: string;
  action: string;
}

export interface RecommendationReport {
  app_id: number;
  app_name: string;
  generated_at: string;
  keyword_recommendations: {
    prioritise: KeywordRec[];
    defend: KeywordRec[];
    target_gaps: KeywordRec[];
    drop: KeywordRec[];
  };
  sentiment_recommendations: {
    error?: string;
    overall_sentiment?: string;
    positive_pct?: number;
    negative_pct?: number;
    avg_rating?: number;
    priority_fix?: string | null;
    top_complaints?: ReviewTheme[];
    top_praise?: ReviewTheme[];
    sentiment_summary?: string | null;
  };
  competitor_recommendations: {
    error?: string;
    top_competitor?: string;
    competitor_score?: number | null;
    competitor_advantages?: string[];
    our_advantages?: string[];
    missing_keywords?: string[];
    recommendation?: string | null;
  };
  description_recommendation: string | null;
  priority_actions: PriorityAction[];
}

export interface KeywordRec {
  keyword: string;
  opportunity_score?: number;
  proxy_opportunity?: number | null;
  revised_opportunity?: number | null;
  gap_competitor?: string | null;
  rank?: number | null;
  trend?: string;
}

export interface ReviewTheme {
  theme: string;
  count: number;
  example_quote: string;
}

export interface CollectStart {
  job_id: string;
  status: string;
}

export interface CollectJob {
  job_id: string;
  status: "running" | "done" | "error";
  detail?: string;
  /** Human-readable description of the pipeline stage currently running. */
  step?: string;
  step_index?: number;
  step_total?: number;
  result?: {
    app_id: number;
    app_name: string;
    country: string;
    reviews_saved: number;
    keywords_tracked: number;
    seed_warning: string | null;
    collected_at: string;
  };
}
