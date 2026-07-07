"use client";

/** Recommendations — priority actions, keyword buckets, AI insights. */

import { useState } from "react";
import { usePageContext } from "@/lib/context";
import { useRecommendations } from "@/lib/hooks";
import { countryLabel } from "@/lib/countries";
import type { KeywordRec } from "@/lib/types";
import {
  Badge,
  Card,
  CheckboxRow,
  EmptyState,
  PageTitle,
  SectionTitle,
  Spinner,
} from "@/components/ui";

const BUCKETS: {
  key: "prioritise" | "defend" | "target_gaps" | "drop";
  label: string;
  caption: string;
  color: "green" | "blue" | "amber" | "neutral";
}[] = [
  { key: "prioritise", label: "🟢 Prioritise", caption: "High opportunity, unranked — go after these.", color: "green" },
  { key: "defend", label: "🔵 Defend", caption: "Already ranking top 10 — protect these.", color: "blue" },
  { key: "target_gaps", label: "🟡 Target gaps", caption: "Competitors rank for these, you don't.", color: "amber" },
  { key: "drop", label: "⚫ Drop", caption: "Low opportunity — deprioritise.", color: "neutral" },
];

function score(kw: KeywordRec): number {
  return kw.opportunity_score ?? kw.revised_opportunity ?? kw.proxy_opportunity ?? 0;
}

export default function RecommendationsPage() {
  const { appId, country } = usePageContext();
  const [useLlm, setUseLlm] = useState(false);
  const { data, isLoading, isFetching } = useRecommendations(appId, country, useLlm);

  const priorityColor = { high: "red", medium: "amber", low: "green" } as const;

  return (
    <div className="mx-auto max-w-6xl">
      <PageTitle title="⭐ Recommendations" subtitle={countryLabel(country)} />

      <Card className="mb-6">
        <CheckboxRow
          label="Use AI for deeper analysis"
          help="Competitor advantage comparison and a description rewrite (uses API credits, takes ~10s)."
          checked={useLlm}
          onChange={setUseLlm}
        />
      </Card>

      {isLoading || isFetching ? (
        <div className="flex flex-col items-center gap-3 py-24">
          <Spinner className="size-8" />
          <p className="text-sm text-neutral-500">
            {useLlm ? "Generating AI recommendations…" : "Generating recommendations…"}
          </p>
        </div>
      ) : !data ? (
        <EmptyState>No recommendations yet — run a collection first.</EmptyState>
      ) : (
        <>
          {/* ── Priority actions ────────────────────────────────────── */}
          <Card>
            <SectionTitle>🎯 Priority actions</SectionTitle>
            {data.priority_actions?.length ? (
              <ul className="space-y-2">
                {data.priority_actions.map((a, i) => (
                  <li
                    key={i}
                    className="flex items-start gap-3 rounded-lg border border-neutral-100 bg-neutral-50 p-3"
                  >
                    <Badge color={priorityColor[a.priority] ?? "neutral"}>
                      {a.priority.toUpperCase()}
                    </Badge>
                    <span className="text-sm text-neutral-700">
                      <span className="mr-2 rounded bg-neutral-200 px-1.5 py-0.5 font-mono text-[10px] uppercase text-neutral-600">
                        {a.area}
                      </span>
                      {a.action}
                    </span>
                  </li>
                ))}
              </ul>
            ) : (
              <EmptyState>No priority actions generated.</EmptyState>
            )}
          </Card>

          {/* ── Keyword buckets ─────────────────────────────────────── */}
          <Card className="mt-6">
            <SectionTitle>🔑 Keyword recommendations</SectionTitle>
            <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
              {BUCKETS.map((b) => {
                const kws = data.keyword_recommendations?.[b.key] ?? [];
                return (
                  <div key={b.key} className="rounded-lg border border-neutral-100 p-3">
                    <p className="text-sm font-semibold text-neutral-800">{b.label}</p>
                    <p className="mb-2 text-xs text-neutral-400">{b.caption}</p>
                    {kws.length ? (
                      <ul className="space-y-1">
                        {kws.slice(0, 10).map((kw) => (
                          <li
                            key={kw.keyword}
                            className="flex items-center justify-between gap-2 text-sm"
                          >
                            <span className="truncate text-neutral-700">{kw.keyword}</span>
                            <span className="font-mono text-xs text-neutral-400">
                              {score(kw).toFixed(2)}
                            </span>
                          </li>
                        ))}
                      </ul>
                    ) : (
                      <p className="text-sm text-neutral-300">—</p>
                    )}
                  </div>
                );
              })}
            </div>
          </Card>

          {/* ── Sentiment insights ──────────────────────────────────── */}
          <Card className="mt-6">
            <SectionTitle>💬 Sentiment insights</SectionTitle>
            {data.sentiment_recommendations?.error ? (
              <EmptyState>{data.sentiment_recommendations.error}</EmptyState>
            ) : (
              <>
                <div className="grid gap-6 md:grid-cols-2">
                  <div>
                    <p className="mb-2 text-sm font-semibold text-neutral-800">
                      Top complaints
                    </p>
                    {data.sentiment_recommendations?.top_complaints?.length ? (
                      <ul className="space-y-2">
                        {data.sentiment_recommendations.top_complaints.map((t, i) => (
                          <li key={i} className="rounded-lg bg-red-50 p-2.5 text-sm">
                            <span className="font-medium text-red-800">
                              {t.theme}
                            </span>{" "}
                            <span className="text-xs text-red-500">×{t.count}</span>
                            <p className="mt-0.5 text-xs italic text-red-600">
                              “{t.example_quote}”
                            </p>
                          </li>
                        ))}
                      </ul>
                    ) : (
                      <p className="text-sm text-neutral-400">
                        {useLlm ? "—" : "Enable AI above for theme extraction."}
                      </p>
                    )}
                  </div>
                  <div>
                    <p className="mb-2 text-sm font-semibold text-neutral-800">
                      Top praise
                    </p>
                    {data.sentiment_recommendations?.top_praise?.length ? (
                      <ul className="space-y-2">
                        {data.sentiment_recommendations.top_praise.map((t, i) => (
                          <li key={i} className="rounded-lg bg-green-50 p-2.5 text-sm">
                            <span className="font-medium text-green-800">
                              {t.theme}
                            </span>{" "}
                            <span className="text-xs text-green-500">×{t.count}</span>
                            <p className="mt-0.5 text-xs italic text-green-600">
                              “{t.example_quote}”
                            </p>
                          </li>
                        ))}
                      </ul>
                    ) : (
                      <p className="text-sm text-neutral-400">
                        {useLlm ? "—" : "Enable AI above for theme extraction."}
                      </p>
                    )}
                  </div>
                </div>
                {data.sentiment_recommendations?.sentiment_summary && (
                  <p className="mt-4 rounded-lg bg-blue-50 p-3 text-sm text-blue-800">
                    {data.sentiment_recommendations.sentiment_summary}
                  </p>
                )}
                {data.sentiment_recommendations?.priority_fix && (
                  <p className="mt-2 rounded-lg bg-amber-50 p-3 text-sm text-amber-800">
                    <b>Priority fix:</b> {data.sentiment_recommendations.priority_fix}
                  </p>
                )}
              </>
            )}
          </Card>

          {/* ── Competitor insights ─────────────────────────────────── */}
          <Card className="mt-6">
            <SectionTitle>🏆 Competitor insights</SectionTitle>
            {data.competitor_recommendations?.error ? (
              <EmptyState>
                No competitor insights yet — collect the app so it has competitors.
              </EmptyState>
            ) : (
              <>
                {data.competitor_recommendations?.top_competitor && (
                  <p className="mb-3 text-xs text-neutral-500">
                    Compared against your top competitor:{" "}
                    <b>{data.competitor_recommendations.top_competitor}</b>
                  </p>
                )}
                {!useLlm &&
                !data.competitor_recommendations?.competitor_advantages?.length ? (
                  <p className="text-sm text-neutral-400">
                    Enable AI above for the advantage comparison.
                  </p>
                ) : (
                  <div className="grid gap-6 md:grid-cols-2">
                    <div>
                      <p className="mb-2 text-sm font-semibold text-neutral-800">
                        Competitor advantages
                      </p>
                      <ul className="list-disc space-y-1 pl-5 text-sm text-neutral-700">
                        {(data.competitor_recommendations?.competitor_advantages ?? []).map(
                          (x, i) => (
                            <li key={i}>{x}</li>
                          )
                        )}
                      </ul>
                    </div>
                    <div>
                      <p className="mb-2 text-sm font-semibold text-neutral-800">
                        Your advantages
                      </p>
                      <ul className="list-disc space-y-1 pl-5 text-sm text-neutral-700">
                        {(data.competitor_recommendations?.our_advantages ?? []).map(
                          (x, i) => (
                            <li key={i}>{x}</li>
                          )
                        )}
                      </ul>
                    </div>
                  </div>
                )}
                {!!data.competitor_recommendations?.missing_keywords?.length && (
                  <div className="mt-4">
                    <p className="mb-1.5 text-sm font-semibold text-neutral-800">
                      Missing keywords
                    </p>
                    <div className="flex flex-wrap gap-1.5">
                      {data.competitor_recommendations.missing_keywords.map((kw) => (
                        <Badge key={kw} color="indigo">
                          {kw}
                        </Badge>
                      ))}
                    </div>
                  </div>
                )}
                {data.competitor_recommendations?.recommendation && (
                  <p className="mt-4 rounded-lg bg-blue-50 p-3 text-sm text-blue-800">
                    {data.competitor_recommendations.recommendation}
                  </p>
                )}
              </>
            )}
          </Card>

          {/* ── Description rewrite ─────────────────────────────────── */}
          <Card className="mt-6">
            <SectionTitle>✍️ Suggested description rewrite</SectionTitle>
            {data.description_recommendation ? (
              <>
                <p className="whitespace-pre-wrap rounded-lg bg-neutral-50 p-4 text-sm leading-relaxed text-neutral-700">
                  {data.description_recommendation}
                </p>
                <p className="mt-2 text-xs text-neutral-400">
                  {data.description_recommendation.length} / 4000 characters
                </p>
              </>
            ) : (
              <p className="text-sm text-neutral-400">
                {useLlm
                  ? "Couldn’t generate a rewrite — the AI model may be busy; try again."
                  : "Enable AI above to generate a description rewrite."}
              </p>
            )}
          </Card>
        </>
      )}
    </div>
  );
}
