"use client";

/** Rankings — keyword rank tracking and velocity. */

import { useMemo, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Loader2, Plus, RefreshCw, Trash2 } from "lucide-react";
import { apiDelete, apiPost } from "@/lib/api";
import { usePageContext } from "@/lib/context";
import { useRankings } from "@/lib/hooks";
import { countryLabel } from "@/lib/countries";
import {
  Button,
  Card,
  DeltaCell,
  EmptyState,
  Input,
  MetricCard,
  PageTitle,
  SectionTitle,
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

  const remove = useMutation({
    mutationFn: (keyword: string) =>
      apiDelete(`/app/${appId}/rankings/keyword`, { keyword, country }),
    onSuccess: invalidate,
  });

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
                  <th className="py-2 pr-3">Trend</th>
                  <th className="py-2"></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-neutral-100">
                {sorted.map((r) => (
                  <tr key={r.keyword} className="group">
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
                    <td className="py-2.5 pr-3">
                      <TrendBadge trend={r.trend} />
                    </td>
                    <td className="py-2.5 text-right">
                      <button
                        onClick={() => remove.mutate(r.keyword)}
                        disabled={remove.isPending}
                        title="Stop tracking this keyword"
                        className="rounded p-1.5 text-neutral-300 opacity-0 transition hover:bg-red-50 hover:text-red-500 group-hover:opacity-100"
                      >
                        <Trash2 className="size-4" />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        </>
      )}
    </div>
  );
}