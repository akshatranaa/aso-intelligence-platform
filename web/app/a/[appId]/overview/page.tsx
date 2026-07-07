"use client";

/** Overview — key metrics and snapshots for the active app+country. */

import Link from "next/link";
import { usePageContext } from "@/lib/context";
import {
  useApp,
  useRankings,
  useRecommendations,
  useSentiment,
} from "@/lib/hooks";
import { countryLabel } from "@/lib/countries";
import {
  Badge,
  Card,
  DeltaCell,
  EmptyState,
  MetricCard,
  PageTitle,
  SectionTitle,
  Spinner,
} from "@/components/ui";

function fmt(n: number | null | undefined): string {
  return n == null ? "—" : n.toLocaleString();
}

export default function OverviewPage() {
  const { appId, country } = usePageContext();
  const { data: app, isLoading } = useApp(appId, country);
  const { data: sentiment } = useSentiment(appId, country);
  const { data: rankings } = useRankings(appId, country);
  const { data: recs } = useRecommendations(appId, country, false);

  if (isLoading || !app) {
    return (
      <div className="flex justify-center py-24">
        <Spinner className="size-8" />
      </div>
    );
  }

  const topRankings = (rankings?.rankings ?? [])
    .filter((r) => r.rank != null)
    .sort((a, b) => (a.rank ?? 999) - (b.rank ?? 999))
    .slice(0, 5);

  const priorityColor = { high: "red", medium: "amber", low: "green" } as const;

  return (
    <div className="mx-auto max-w-6xl">
      <PageTitle
        title={app.name}
        subtitle={`${app.category ?? ""} · ${app.seller_name ?? ""} · ${countryLabel(
          country ?? app.country
        )}`}
      />

      {/* ── Key metrics ─────────────────────────────────────────────── */}
      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <MetricCard label="Avg Rating" value={`${app.avg_rating?.toFixed(2) ?? "—"} ★`} />
        <MetricCard label="Total Ratings" value={fmt(app.rating_count)} />
        <MetricCard
          label="Price"
          value={app.price ? `$${app.price.toFixed(2)}` : "Free"}
        />
        <MetricCard label="Version" value={app.version ?? "—"} />
      </div>

      {/* ── Sentiment snapshot ──────────────────────────────────────── */}
      <div className="mt-6 grid gap-6 lg:grid-cols-2">
        <Card>
          <div className="mb-3 flex items-center justify-between">
            <SectionTitle>💬 Sentiment snapshot</SectionTitle>
            <Link
              href={`/a/${appId}/sentiment${country ? `?country=${country}` : ""}`}
              className="text-xs font-medium text-indigo-600 hover:underline"
            >
              View details →
            </Link>
          </div>
          {sentiment ? (
            <div className="grid grid-cols-2 gap-4">
              <MetricCard label="Recent reviews" value={sentiment.total_reviews} />
              <MetricCard
                label="Reviews avg"
                value={`${sentiment.avg_rating} ★`}
                hint="Average of the recent reviews collected — not the store's all-time rating"
              />
              <MetricCard
                label="Positive"
                value={<span className="text-green-600">{sentiment.positive_pct}%</span>}
              />
              <MetricCard
                label="Negative"
                value={<span className="text-red-600">{sentiment.negative_pct}%</span>}
              />
            </div>
          ) : (
            <EmptyState>No sentiment data for this country yet.</EmptyState>
          )}
        </Card>

        {/* ── Rankings snapshot ─────────────────────────────────────── */}
        <Card>
          <div className="mb-3 flex items-center justify-between">
            <SectionTitle>📈 Best keyword ranks</SectionTitle>
            <Link
              href={`/a/${appId}/rankings${country ? `?country=${country}` : ""}`}
              className="text-xs font-medium text-indigo-600 hover:underline"
            >
              View all →
            </Link>
          </div>
          {topRankings.length ? (
            <ul className="divide-y divide-neutral-100">
              {topRankings.map((r) => (
                <li key={r.keyword} className="flex items-center justify-between py-2">
                  <span className="truncate text-sm text-neutral-700">{r.keyword}</span>
                  <span className="flex items-center gap-3">
                    <DeltaCell delta={r.delta} />
                    <span className="w-12 text-right text-sm font-semibold text-neutral-900">
                      #{r.rank}
                    </span>
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <EmptyState>No ranked keywords for this country yet.</EmptyState>
          )}
        </Card>
      </div>

      {/* ── Priority actions ────────────────────────────────────────── */}
      <Card className="mt-6">
        <SectionTitle>⭐ Priority actions</SectionTitle>
        {recs?.priority_actions?.length ? (
          <ul className="space-y-2">
            {recs.priority_actions.map((a, i) => (
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
          <EmptyState>No priority actions yet — run a collection first.</EmptyState>
        )}
      </Card>
    </div>
  );
}
