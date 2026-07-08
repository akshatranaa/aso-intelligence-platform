"use client";

/** TanStack Query hooks for every backend endpoint. */

import { useQuery } from "@tanstack/react-query";
import { apiGet } from "./api";
import type {
  AppDetail,
  AppSummary,
  CollectJob,
  CompareResult,
  Competitor,
  RankingRow,
  RecommendationReport,
  Review,
  SentimentSummary,
} from "./types";

export function useApps() {
  return useQuery({
    queryKey: ["apps"],
    queryFn: () => apiGet<{ total: number; apps: AppSummary[] }>("/apps"),
  });
}

export function useApp(appId: number | null, country?: string) {
  return useQuery({
    queryKey: ["app", appId, country],
    queryFn: () => apiGet<AppDetail>(`/app/${appId}`, { country }),
    enabled: appId != null,
  });
}

export function useSentiment(appId: number | null, country?: string) {
  return useQuery({
    queryKey: ["sentiment", appId, country],
    queryFn: () => apiGet<SentimentSummary>(`/app/${appId}/sentiment`, { country }),
    enabled: appId != null,
    retry: false, // 404 just means "no data yet"
  });
}

export function useReviews(appId: number | null, country?: string) {
  return useQuery({
    queryKey: ["reviews", appId, country],
    queryFn: () =>
      apiGet<{ total: number; reviews: Review[] }>(`/app/${appId}/reviews`, { country }),
    enabled: appId != null,
  });
}

export function useRankings(appId: number | null, country?: string) {
  return useQuery({
    queryKey: ["rankings", appId, country],
    queryFn: () =>
      apiGet<{ total: number; rankings: RankingRow[] }>(`/app/${appId}/rankings`, { country }),
    enabled: appId != null,
  });
}

export function useSeeds(appId: number | null, country?: string) {
  return useQuery({
    queryKey: ["seeds", appId, country],
    queryFn: () =>
      apiGet<{ seeds: string[] }>(`/app/${appId}/seeds`, { country }),
    enabled: appId != null,
  });
}

export function useCompetitors(appId: number | null, country?: string) {
  return useQuery({
    queryKey: ["competitors", appId, country],
    queryFn: () =>
      apiGet<{ total: number; tier1: Competitor[]; tier2: Competitor[] }>(
        `/app/${appId}/competitors`,
        { country }
      ),
    enabled: appId != null,
  });
}

export function useRecommendations(
  appId: number | null,
  country?: string,
  useLlm = false
) {
  return useQuery({
    queryKey: ["recommendations", appId, country, useLlm],
    queryFn: () =>
      apiGet<RecommendationReport>(`/app/${appId}/recommendations`, {
        country,
        use_llm: useLlm,
      }),
    enabled: appId != null,
    staleTime: 5 * 60 * 1000, // LLM output is expensive — don't refetch eagerly
  });
}

export function useCompare(
  appId: number | null,
  keyword: string | null,
  n: number,
  country?: string
) {
  return useQuery({
    queryKey: ["compare", appId, keyword, n, country],
    queryFn: () =>
      apiGet<CompareResult>(`/app/${appId}/rankings/compare`, {
        keyword: keyword ?? "",
        n,
        country,
      }),
    enabled: false, // fired manually via refetch() — it's a slow live lookup
    staleTime: Infinity,
  });
}

/** Poll a collect job until it finishes (2s interval, stops on done/error). */
export function useCollectJob(jobId: string | null) {
  return useQuery({
    queryKey: ["collect-job", jobId],
    queryFn: () => apiGet<CollectJob>(`/collect/status/${jobId}`),
    enabled: jobId != null,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "done" || status === "error" ? false : 2000;
    },
  });
}
