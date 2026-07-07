"use client";

/** Rankings — keyword rank tracking, velocity, and competitor comparison. */

import { useMemo, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Bar,
  BarChart,
  Cell,
  LabelList,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Loader2, Plus, RefreshCw } from "lucide-react";
import { apiPost } from "@/lib/api";
import { usePageContext } from "@/lib/context";
import { useCompare, useRankings } from "@/lib/hooks";
import { COUNTRIES, countryLabel } from "@/lib/countries";
import {
  Button,
  Card,
  DeltaCell,
  EmptyState,
  Input,
  MetricCard,
  PageTitle,
  SectionTitle,
  Select,
  Spinner,
  TrendBadge,
} from "@/components/ui";

export default function RankingsPage() {
  const { appId, country } = usePageContext();
  const queryClient = useQueryClient();
  const { data, isLoading } = useRankings(appId, country);
  const rankings = useMemo(() => data?.rankings ?? [], [data?.rankings]);

  const [newKw, setNewKw] = useState("");

  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: ["rankings", appId, country] });

  const track = useMutation({
    mutationFn: (keyword: string) =>
      apiPost(`/app/${appId}/rankings/track`, { keyword, country }),
    onSuccess: () => {
      setNewKw("");
      invalidate();
    },
  });

  const refresh = useMutation({
    mutationFn: () => apiPost(`/app/${appId}/rankings/refresh`, { country }),
    onSuccess: invalidate,
  });

  /* ── Competitor comparison state ─────────────────────────────────── */
  const kwOptions = rankings.map((r) => r.keyword);
  const [cmpKeyword, setCmpKeyword] = useState<string | null>(null);
  const [cmpCountry, setCmpCountry] = useState<string | undefined>(undefined);
  const [cmpN, setCmpN] = useState(5);
  const effectiveKeyword = cmpKeyword ?? kwOptions[0] ?? null;
  const effectiveCountry = cmpCountry ?? country ?? "in";
  const compare = useCompare(appId, effectiveKeyword, cmpN, effectiveCountry);

  const sorted = useMemo(
    () =>
      [...rankings].sort((a, b) => (a.rank ?? 9999) - (b.rank ?? 9999)),
    [rankings]
  );
  const ranked = rankings.filter((r) => r.rank != null);
  const improving = rankings.filter((r) => r.trend === "improving");
  const declining = rankings.filter((r) => r.trend === "declining");

  if (isLoading) {
    return (
      <div className="flex justify-center py-24">
        <Spinner className="size-8" />
      </div>
    );
  }

  const compareData = compare.data
    ? [
        {
          name: `${compare.data.target.name} (you)`,
          rank: compare.data.target.rank,
          fill: "#4f46e5",
        },
        ...compare.data.competitors.map((c) => ({
          name: c.name,
          rank: c.rank,
          fill: "#a5b4fc",
        })),
      ].filter((d) => d.rank != null)
    : [];

  return (
    <div className="mx-auto max-w-6xl">
      <PageTitle title="📈 Keyword Rankings" subtitle={countryLabel(country)}>
        <Button
          variant="outline"
          onClick={() => refresh.mutate()}
          disabled={refresh.isPending}
        >
          {refresh.isPending ? (
            <Loader2 className="size-4 animate-spin" />
          ) : (
            <RefreshCw className="size-4" />
          )}
          Re-run ranking analysis
        </Button>
      </PageTitle>

      {/* ── Track a keyword ─────────────────────────────────────────── */}
      <Card className="mb-6">
        <div className="flex gap-2">
          <Input
            placeholder="Track a new keyword — e.g. secure vpn"
            value={newKw}
            onChange={(e) => setNewKw(e.target.value)}
            onKeyDown={(e) =>
              e.key === "Enter" && newKw.trim() && track.mutate(newKw.trim())
            }
            disabled={track.isPending}
          />
          <Button
            onClick={() => newKw.trim() && track.mutate(newKw.trim())}
            disabled={track.isPending || !newKw.trim()}
          >
            {track.isPending ? (
              <Loader2 className="size-4 animate-spin" />
            ) : (
              <Plus className="size-4" />
            )}
            Track
          </Button>
        </div>
        {track.isError && (
          <p className="mt-2 text-xs text-red-600">
            {track.error instanceof Error ? track.error.message : "Failed to track"}
          </p>
        )}
      </Card>

      {rankings.length === 0 ? (
        <EmptyState>
          No rankings for this country yet — track a keyword above or run a collection.
        </EmptyState>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
            <MetricCard label="Keywords tracked" value={rankings.length} />
            <MetricCard label="Currently ranked" value={ranked.length} />
            <MetricCard
              label="Improving"
              value={<span className="text-green-600">{improving.length}</span>}
            />
            <MetricCard
              label="Declining"
              value={<span className="text-red-600">{declining.length}</span>}
            />
          </div>

          {/* ── Rankings table ──────────────────────────────────────── */}
          <Card className="mt-6">
            <SectionTitle>Keyword overview</SectionTitle>
            <table className="w-full text-sm">
              <thead className="text-left text-xs uppercase tracking-wide text-neutral-400">
                <tr>
                  <th className="py-2 pr-3">Keyword</th>
                  <th className="py-2 pr-3">Rank</th>
                  <th className="py-2 pr-3">Delta</th>
                  <th className="py-2 pr-3">Velocity (avg/day)</th>
                  <th className="py-2">Trend</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-neutral-100">
                {sorted.map((r) => (
                  <tr key={r.keyword}>
                    <td className="py-2.5 pr-3 font-medium text-neutral-800">
                      {r.keyword}
                    </td>
                    <td className="py-2.5 pr-3">
                      {r.rank != null ? (
                        <span className="font-semibold text-neutral-900">#{r.rank}</span>
                      ) : (
                        <span className="text-neutral-400">Unranked</span>
                      )}
                    </td>
                    <td className="py-2.5 pr-3">
                      <DeltaCell delta={r.delta} />
                    </td>
                    <td className="py-2.5 pr-3 text-neutral-600">
                      {r.velocity != null ? r.velocity.toFixed(2) : "—"}
                    </td>
                    <td className="py-2.5">
                      <TrendBadge trend={r.trend} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>

          {/* ── Competitor rank comparison ──────────────────────────── */}
          <Card className="mt-6">
            <SectionTitle>🆚 Competitor rank comparison</SectionTitle>
            <p className="mb-4 text-xs text-neutral-500">
              Live lookup: where do your top competitors rank for a keyword, in any
              country? Lower rank = better. ~1s per competitor.
            </p>
            <div className="flex flex-wrap items-end gap-3">
              <div>
                <label className="mb-1 block text-xs font-medium text-neutral-500">
                  Keyword
                </label>
                <Select
                  className="w-52"
                  value={effectiveKeyword ?? ""}
                  onChange={(e) => setCmpKeyword(e.target.value)}
                >
                  {kwOptions.map((k) => (
                    <option key={k} value={k}>
                      {k}
                    </option>
                  ))}
                </Select>
              </div>
              <div>
                <label className="mb-1 block text-xs font-medium text-neutral-500">
                  Country
                </label>
                <Select
                  className="w-44"
                  value={effectiveCountry}
                  onChange={(e) => setCmpCountry(e.target.value)}
                >
                  {COUNTRIES.map((c) => (
                    <option key={c.code} value={c.code}>
                      {c.flag} {c.label}
                    </option>
                  ))}
                </Select>
              </div>
              <div className="min-w-44 flex-1">
                <label className="mb-1 block text-xs font-medium text-neutral-500">
                  Competitors to compare: {cmpN}
                </label>
                <input
                  type="range"
                  min={1}
                  max={25}
                  value={cmpN}
                  onChange={(e) => setCmpN(Number(e.target.value))}
                  className="w-full accent-indigo-600"
                />
              </div>
              <Button
                onClick={() => compare.refetch()}
                disabled={compare.isFetching || !effectiveKeyword}
              >
                {compare.isFetching && <Loader2 className="size-4 animate-spin" />}
                {compare.isFetching ? `Comparing… (~${cmpN + 1}s)` : "Compare"}
              </Button>
            </div>

            {compare.data && !compare.isFetching && (
              <div className="mt-5">
                <ResponsiveContainer
                  width="100%"
                  height={Math.max(200, compareData.length * 42)}
                >
                  <BarChart data={compareData} layout="vertical" margin={{ left: 12, right: 40 }}>
                    <XAxis type="number" tickLine={false} />
                    <YAxis
                      type="category"
                      dataKey="name"
                      width={220}
                      tickLine={false}
                      axisLine={false}
                      tick={{ fontSize: 12 }}
                    />
                    <Tooltip />
                    <Bar dataKey="rank" radius={[0, 6, 6, 0]}>
                      <LabelList
                        dataKey="rank"
                        position="right"
                        formatter={(v) => `#${v}`}
                        className="text-xs"
                      />
                      {compareData.map((d, i) => (
                        <Cell key={i} fill={d.fill} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
                {compare.data.competitors.some((c) => c.rank == null) && (
                  <p className="mt-2 text-xs text-neutral-400">
                    Unranked for “{compare.data.keyword}”:{" "}
                    {compare.data.competitors
                      .filter((c) => c.rank == null)
                      .map((c) => c.name)
                      .join(", ")}
                  </p>
                )}
              </div>
            )}
          </Card>
        </>
      )}
    </div>
  );
}