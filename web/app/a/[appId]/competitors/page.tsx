"use client";

/** Competitors — AI-judged competitor list with scores, tiers, and charts. */

import { useMemo, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
  ZAxis,
} from "recharts";
import { usePageContext } from "@/lib/context";
import { useApp, useCompetitors } from "@/lib/hooks";
import { countryLabel } from "@/lib/countries";
import type { Competitor } from "@/lib/types";
import {
  Card,
  EmptyState,
  MetricCard,
  PageTitle,
  SectionTitle,
  Spinner,
  cn,
} from "@/components/ui";

function Methodology() {
  const [open, setOpen] = useState(false);
  return (
    <Card className="mb-6 py-3">
      <button
        onClick={() => setOpen(!open)}
        className="flex w-full items-center justify-between text-sm font-medium text-neutral-700"
      >
        ℹ️ How competitors are assessed
        <span className="text-neutral-400">{open ? "▲" : "▼"}</span>
      </button>
      {open && (
        <div className="mt-3 space-y-2 text-sm text-neutral-600">
          <p>
            <b>1. Discovery</b> — we search the App Store for up to 5 seed keywords
            (AI-generated from your app’s function) and collect the top 15 apps for
            each: a pool of ~75 candidates.
          </p>
          <p>
            <b>2. AI relevance judge</b> — a model reads your app and every candidate
            and keeps only genuine direct competitors, so merely-popular apps
            (ChatGPT, Calculator) are excluded.
          </p>
          <p>
            <b>3. Popularity score</b> — kept competitors are ranked:{" "}
            <code className="rounded bg-neutral-100 px-1 text-xs">
              0.70 × min(ratings ÷ 1M, 1) + 0.30 × (avg − 1) ÷ 4
            </code>
          </p>
          <p>
            <b>4. Tiers</b> — Tier 1 = same category as your app <i>and</i> score ≥
            0.40 (closest strong rivals); Tier 2 = every other genuine competitor.
          </p>
        </div>
      )}
    </Card>
  );
}

function CompetitorTable({ apps }: { apps: Competitor[] }) {
  if (!apps.length) return <EmptyState>No competitors in this tier.</EmptyState>;
  return (
    <table className="w-full text-sm">
      <thead className="text-left text-xs uppercase tracking-wide text-neutral-400">
        <tr>
          <th className="py-2 pr-3">App</th>
          <th className="py-2 pr-3">Score</th>
          <th className="py-2 pr-3">Rating</th>
          <th className="py-2 pr-3">Ratings count</th>
          <th className="py-2">Category</th>
        </tr>
      </thead>
      <tbody className="divide-y divide-neutral-100">
        {apps.map((c) => (
          <tr key={c.app_id}>
            <td className="max-w-xs truncate py-2.5 pr-3 font-medium text-neutral-800">
              {c.name}
            </td>
            <td className="py-2.5 pr-3 font-mono text-neutral-600">
              {c.competitor_score?.toFixed(3) ?? "—"}
            </td>
            <td className="py-2.5 pr-3 text-neutral-600">
              {c.avg_rating?.toFixed(2) ?? "—"} ★
            </td>
            <td className="py-2.5 pr-3 text-neutral-600">
              {c.rating_count?.toLocaleString() ?? "—"}
            </td>
            <td className="py-2.5 text-neutral-500">{c.category ?? "—"}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export default function CompetitorsPage() {
  const { appId, country } = usePageContext();
  const { data, isLoading } = useCompetitors(appId, country);
  const { data: app } = useApp(appId, country);
  const [tab, setTab] = useState<"tier1" | "tier2">("tier1");

  const tier1 = useMemo(() => data?.tier1 ?? [], [data?.tier1]);
  const tier2 = useMemo(() => data?.tier2 ?? [], [data?.tier2]);
  const all = useMemo(() => [...tier1, ...tier2], [tier1, tier2]);

  const chartData = useMemo(
    () =>
      [...all]
        .sort((a, b) => (b.competitor_score ?? 0) - (a.competitor_score ?? 0))
        .slice(0, 15)
        .map((c) => ({
          name: c.name.length > 24 ? c.name.slice(0, 24) + "…" : c.name,
          score: c.competitor_score ?? 0,
          fill: c.competitor_tier === "tier1" ? "#4f46e5" : "#a5b4fc",
        })),
    [all]
  );

  const scatterData = useMemo(
    () =>
      all
        .filter((c) => c.avg_rating != null && c.rating_count != null)
        .map((c) => ({
          name: c.name,
          x: c.rating_count!,
          y: c.avg_rating!,
          tier: c.competitor_tier,
        })),
    [all]
  );

  if (isLoading) {
    return (
      <div className="flex justify-center py-24">
        <Spinner className="size-8" />
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-6xl">
      <PageTitle title="🏆 Competitor Analysis" subtitle={countryLabel(country)} />
      <Methodology />

      {!all.length ? (
        <EmptyState>
          No competitors for this country yet — run a collection first.
        </EmptyState>
      ) : (
        <>
          <div className="grid grid-cols-3 gap-4">
            <MetricCard label="Total competitors" value={all.length} />
            <MetricCard label="Tier 1 (top, same-category)" value={tier1.length} />
            <MetricCard label="Tier 2 (other relevant)" value={tier2.length} />
          </div>

          <Card className="mt-6">
            <SectionTitle>Top competitors by score</SectionTitle>
            <ResponsiveContainer width="100%" height={Math.max(220, chartData.length * 32)}>
              <BarChart data={chartData} layout="vertical" margin={{ left: 12, right: 24 }}>
                <XAxis type="number" domain={[0, 1]} tickLine={false} />
                <YAxis
                  type="category"
                  dataKey="name"
                  width={190}
                  tickLine={false}
                  axisLine={false}
                  tick={{ fontSize: 12 }}
                />
                <Tooltip />
                <Bar dataKey="score" radius={[0, 6, 6, 0]}>
                  {chartData.map((d, i) => (
                    <Cell key={i} fill={d.fill} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
            <p className="mt-1 text-xs text-neutral-400">
              <span className="mr-3 inline-flex items-center gap-1">
                <span className="size-2.5 rounded-full bg-indigo-600" /> Tier 1
              </span>
              <span className="inline-flex items-center gap-1">
                <span className="size-2.5 rounded-full bg-indigo-300" /> Tier 2
              </span>
            </p>
          </Card>

          <Card className="mt-6">
            <div className="mb-4 flex gap-2">
              {(["tier1", "tier2"] as const).map((t) => (
                <button
                  key={t}
                  onClick={() => setTab(t)}
                  className={cn(
                    "rounded-lg px-3 py-1.5 text-sm font-medium",
                    tab === t
                      ? "bg-indigo-50 text-indigo-700"
                      : "text-neutral-500 hover:bg-neutral-100"
                  )}
                >
                  {t === "tier1" ? `🥇 Tier 1 (${tier1.length})` : `🥈 Tier 2 (${tier2.length})`}
                </button>
              ))}
            </div>
            <CompetitorTable apps={tab === "tier1" ? tier1 : tier2} />
          </Card>

          {scatterData.length > 0 && (
            <Card className="mt-6">
              <SectionTitle>Rating vs popularity</SectionTitle>
              <ResponsiveContainer width="100%" height={320}>
                <ScatterChart margin={{ left: 12, right: 24, bottom: 8 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#e5e5e5" />
                  <XAxis
                    type="number"
                    dataKey="x"
                    name="Ratings"
                    scale="log"
                    domain={["auto", "auto"]}
                    tickFormatter={(v: number) =>
                      v >= 1_000_000 ? `${v / 1_000_000}M` : v >= 1000 ? `${v / 1000}K` : String(v)
                    }
                    tick={{ fontSize: 12 }}
                  />
                  <YAxis
                    type="number"
                    dataKey="y"
                    name="Avg rating"
                    domain={[1, 5]}
                    tick={{ fontSize: 12 }}
                  />
                  <ZAxis range={[80, 81]} />
                  <Tooltip
                    cursor={{ strokeDasharray: "3 3" }}
                    content={({ payload }) =>
                      payload?.length ? (
                        <div className="rounded-lg border border-neutral-200 bg-white p-2 text-xs shadow">
                          <b>{(payload[0].payload as { name: string }).name}</b>
                          <br />
                          {(payload[0].payload as { x: number }).x.toLocaleString()} ratings ·{" "}
                          {(payload[0].payload as { y: number }).y.toFixed(2)} ★
                        </div>
                      ) : null
                    }
                  />
                  <Scatter
                    data={scatterData.filter((d) => d.tier === "tier1")}
                    fill="#4f46e5"
                  />
                  <Scatter
                    data={scatterData.filter((d) => d.tier === "tier2")}
                    fill="#a5b4fc"
                  />
                  {app?.rating_count != null && app?.avg_rating != null && (
                    <Scatter
                      data={[{ name: `${app.name} (you)`, x: app.rating_count, y: app.avg_rating }]}
                      fill="#dc2626"
                      shape="star"
                    />
                  )}
                </ScatterChart>
              </ResponsiveContainer>
              <p className="mt-1 text-xs text-neutral-400">
                <span className="mr-3 inline-flex items-center gap-1">
                  <span className="size-2.5 rounded-full bg-red-600" /> You
                </span>
                <span className="mr-3 inline-flex items-center gap-1">
                  <span className="size-2.5 rounded-full bg-indigo-600" /> Tier 1
                </span>
                <span className="inline-flex items-center gap-1">
                  <span className="size-2.5 rounded-full bg-indigo-300" /> Tier 2
                </span>{" "}
                · X axis is logarithmic
              </p>
            </Card>
          )}

        </>
      )}
    </div>
  );
}
