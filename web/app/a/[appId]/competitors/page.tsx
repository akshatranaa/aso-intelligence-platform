"use client";

/** Competitors — AI-judged competitor list with scores, tiers, and charts. */

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  LabelList,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
  ZAxis,
} from "recharts";
import { Loader2, Plus, RotateCcw, Trash2, X } from "lucide-react";
import { apiDelete, apiPost } from "@/lib/api";
import { usePageContext } from "@/lib/context";
import {
  useApp,
  useCollectJob,
  useCompare,
  useCompetitors,
  useRankings,
  useSeeds,
} from "@/lib/hooks";
import { COUNTRIES, countryLabel } from "@/lib/countries";
import type { Competitor } from "@/lib/types";
import {
  Button,
  Card,
  EmptyState,
  Input,
  MetricCard,
  PageTitle,
  SectionTitle,
  Select,
  Spinner,
  cn,
} from "@/components/ui";

function SeedKeywordsCard({ appId, country }: { appId: number; country?: string }) {
  const queryClient = useQueryClient();
  const { data } = useSeeds(appId, country);
  const serverSeeds = useMemo(() => data?.seeds ?? [], [data?.seeds]);

  // `draft` is the working copy of the keyword list. null = "in sync with the
  // server"; once you add/remove anything it holds your pending edits.
  const [draft, setDraft] = useState<string[] | null>(null);
  const [newKw, setNewKw] = useState("");
  const [jobId, setJobId] = useState<string | null>(null);
  const { data: job } = useCollectJob(jobId);
  const rediscovering = jobId != null && (!job || job.status === "running");
  const failed = job?.status === "error" ? job.detail : null;

  useEffect(() => {
    if (job?.status === "done") {
      queryClient.invalidateQueries({ queryKey: ["competitors", appId, country] });
      queryClient.invalidateQueries({ queryKey: ["seeds", appId, country] });
      // Reset local edit state once the save job finishes (async completion —
      // a legitimate effect that the set-state-in-effect rule over-flags).
      /* eslint-disable react-hooks/set-state-in-effect */
      setDraft(null); // re-sync to the freshly saved server list
      setJobId(null);
      /* eslint-enable react-hooks/set-state-in-effect */
    }
  }, [job?.status, appId, country, queryClient]);

  const chips = draft ?? serverSeeds;
  const added = chips.filter((k) => !serverSeeds.includes(k));
  const removed = serverSeeds.filter((k) => !chips.includes(k));
  const dirty = added.length > 0 || removed.length > 0;

  const removeKw = (k: string) => setDraft(chips.filter((x) => x !== k));
  const addKw = () => {
    const k = newKw.trim().toLowerCase();
    if (k && !chips.includes(k)) setDraft([...chips, k]);
    setNewKw("");
  };
  const reset = () => {
    setDraft(null);
    setNewKw("");
  };

  async function save() {
    if (!chips.length || !dirty) return;
    const res = await apiPost<{ job_id: string }>(
      `/app/${appId}/competitors/rediscover`,
      { kw: chips, country }
    );
    if (res?.job_id) setJobId(res.job_id);
  }

  return (
    <Card className="mb-6">
      <SectionTitle>🌱 Seed keywords</SectionTitle>
      <p className="mb-4 text-xs text-neutral-500">
        These keywords discover this app&apos;s top performers. Add or remove any,
        then re-analyse for {countryLabel(country)}.
      </p>

      {rediscovering ? (
        <div className="flex items-center gap-2 rounded-lg border border-indigo-100 bg-indigo-50 p-4 text-sm text-indigo-800">
          <Spinner /> Re-analysing top performers from your keywords… this can take
          up to a minute.
        </div>
      ) : (
        <>
          {/* Each chip is deletable at all times */}
          <div className="flex flex-wrap gap-2">
            {chips.length === 0 && (
              <span className="text-sm text-neutral-400">
                No keywords yet — add one below to run the analysis.
              </span>
            )}
            {chips.map((k) => {
              const isNew = added.includes(k);
              return (
                <span
                  key={k}
                  className={cn(
                    "group inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-sm transition",
                    isNew
                      ? "border-emerald-200 bg-emerald-50 text-emerald-700"
                      : "border-neutral-200 bg-neutral-50 text-neutral-700"
                  )}
                >
                  {k}
                  <button
                    onClick={() => removeKw(k)}
                    className="text-neutral-400 hover:text-red-500"
                    title={`Remove "${k}"`}
                    aria-label={`Remove ${k}`}
                  >
                    <X className="size-3.5" />
                  </button>
                </span>
              );
            })}
          </div>

          {/* Always-visible add box */}
          <div className="mt-3 flex gap-2">
            <Input
              placeholder="Add a keyword — e.g. instant delivery"
              value={newKw}
              onChange={(e) => setNewKw(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && addKw()}
            />
            <Button variant="outline" onClick={addKw} disabled={!newKw.trim()}>
              <Plus className="size-4" /> Add
            </Button>
          </div>

          {/* Re-analyse only when there are pending changes */}
          <div className="mt-4 flex flex-wrap items-center gap-3 border-t border-neutral-100 pt-4">
            <Button onClick={save} disabled={!dirty || chips.length === 0}>
              <RotateCcw className="size-4" /> Save &amp; re-analyse
            </Button>
            {dirty && (
              <Button variant="ghost" onClick={reset}>
                Discard changes
              </Button>
            )}
            {dirty ? (
              <span className="text-xs text-neutral-500">
                {added.length > 0 && (
                  <span className="text-emerald-600">+{added.length} added</span>
                )}
                {added.length > 0 && removed.length > 0 && " · "}
                {removed.length > 0 && (
                  <span className="text-red-500">−{removed.length} removed</span>
                )}
                {" — unsaved"}
              </span>
            ) : (
              <span className="text-xs text-neutral-400">No unsaved changes</span>
            )}
            {chips.length === 0 && dirty && (
              <span className="text-xs text-red-500">Keep at least one keyword.</span>
            )}
          </div>
          {failed && (
            <p className="mt-3 rounded-lg bg-red-50 p-3 text-sm text-red-700">
              Re-analysis failed: {failed}
            </p>
          )}
        </>
      )}
    </Card>
  );
}

function CompareCard({
  appId,
  country,
}: {
  appId: number;
  country?: string;
}) {
  const { data: rankData } = useRankings(appId, country);
  const kwOptions = (rankData?.rankings ?? []).map((r) => r.keyword);

  const [keyword, setKeyword] = useState<string | null>(null);
  const [cmpCountry, setCmpCountry] = useState<string | undefined>(undefined);
  const [n, setN] = useState(5);
  const effKeyword = keyword ?? kwOptions[0] ?? null;
  const effCountry = cmpCountry ?? country ?? "in";
  const compare = useCompare(appId, effKeyword, n, effCountry);

  const chart = compare.data
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
    <Card className="mb-6">
      <SectionTitle>🆚 Competitor rank comparison</SectionTitle>
      <p className="mb-4 text-xs text-neutral-500">
        Live lookup: where do your top competitors rank for a keyword, in any
        country? Lower rank = better. ~1s per competitor.
      </p>
      {kwOptions.length === 0 ? (
        <EmptyState>Track some keywords on the Rankings page first.</EmptyState>
      ) : (
        <>
          <div className="flex flex-wrap items-end gap-3">
            <div>
              <label className="mb-1 block text-xs font-medium text-neutral-500">
                Keyword
              </label>
              <Select
                className="w-52"
                value={effKeyword ?? ""}
                onChange={(e) => setKeyword(e.target.value)}
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
                value={effCountry}
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
                Competitors to compare: {n}
              </label>
              <input
                type="range"
                min={1}
                max={25}
                value={n}
                onChange={(e) => setN(Number(e.target.value))}
                className="w-full accent-indigo-600"
              />
            </div>
            <Button
              onClick={() => compare.refetch()}
              disabled={compare.isFetching || !effKeyword}
            >
              {compare.isFetching && <Loader2 className="size-4 animate-spin" />}
              {compare.isFetching ? `Comparing… (~${n + 1}s)` : "Compare"}
            </Button>
          </div>

          {compare.data && !compare.isFetching && (
            <div className="mt-5">
              <ResponsiveContainer width="100%" height={Math.max(200, chart.length * 42)}>
                <BarChart data={chart} layout="vertical" margin={{ left: 12, right: 40 }}>
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
                    <LabelList dataKey="rank" position="right" formatter={(v) => `#${v}`} className="text-xs" />
                    {chart.map((d, i) => (
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
        </>
      )}
    </Card>
  );
}

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

function CompetitorTable({
  apps,
  onRemove,
  removingId,
}: {
  apps: Competitor[];
  onRemove: (id: number) => void;
  removingId: number | null;
}) {
  if (!apps.length) return <EmptyState>No competitors in this tier.</EmptyState>;
  return (
    <table className="w-full text-sm">
      <thead className="text-left text-xs uppercase tracking-wide text-neutral-400">
        <tr>
          <th className="py-2 pr-3">App</th>
          <th className="py-2 pr-3">Score</th>
          <th className="py-2 pr-3">Rating</th>
          <th className="py-2 pr-3">Ratings count</th>
          <th className="py-2 pr-3">Category</th>
          <th className="py-2"></th>
        </tr>
      </thead>
      <tbody className="divide-y divide-neutral-100">
        {apps.map((c) => (
          <tr key={c.app_id} className="group">
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
            <td className="py-2.5 pr-3 text-neutral-500">{c.category ?? "—"}</td>
            <td className="py-2.5 text-right">
              <button
                onClick={() => onRemove(c.app_id)}
                disabled={removingId === c.app_id}
                title="Remove this competitor (deletes it from the database)"
                className="rounded p-1.5 text-neutral-300 opacity-0 transition hover:bg-red-50 hover:text-red-500 group-hover:opacity-100"
              >
                {removingId === c.app_id ? (
                  <Loader2 className="size-4 animate-spin" />
                ) : (
                  <Trash2 className="size-4" />
                )}
              </button>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export default function CompetitorsPage() {
  const { appId, country } = usePageContext();
  const queryClient = useQueryClient();
  const { data, isLoading } = useCompetitors(appId, country);
  const { data: app } = useApp(appId, country);
  const [tab, setTab] = useState<"tier1" | "tier2">("tier1");

  const removeCompetitor = useMutation({
    mutationFn: (compId: number) =>
      apiDelete(`/app/${appId}/competitors/${compId}`, { country }),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["competitors", appId, country] }),
  });

  const tier1 = useMemo(() => data?.tier1 ?? [], [data?.tier1]);
  const tier2 = useMemo(() => data?.tier2 ?? [], [data?.tier2]);
  const all = useMemo(() => [...tier1, ...tier2], [tier1, tier2]);

  const chartData = useMemo(
    () =>
      [...all]
        .sort((a, b) => (b.competitor_score ?? 0) - (a.competitor_score ?? 0))
        .slice(0, 15)
        .map((c) => ({
          app_id: c.app_id,
          fullName: c.name,
          name: c.name.length > 24 ? c.name.slice(0, 24) + "…" : c.name,
          score: c.competitor_score ?? 0,
          fill: c.competitor_tier === "tier1" ? "#4f46e5" : "#a5b4fc",
        })),
    [all]
  );

  // Click a bar to permanently remove that competitor (same endpoint as the
  // tier-table trash button). Confirm first — a stray click deletes for real.
  const removeFromChart = (datum: { app_id?: number; fullName?: string }) => {
    const id = datum?.app_id;
    if (id == null || removeCompetitor.isPending) return;
    if (
      window.confirm(
        `Remove "${datum.fullName ?? "this competitor"}" from your top performers?\n\n` +
          "This deletes it permanently from the database for this country."
      )
    ) {
      removeCompetitor.mutate(id);
    }
  };

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
      <PageTitle title="🏆 Top Performers of App Store" subtitle={countryLabel(country)} />

      <SeedKeywordsCard appId={appId} country={country} />

      <CompareCard appId={appId} country={country} />

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
                <Bar
                  dataKey="score"
                  radius={[0, 6, 6, 0]}
                  cursor="pointer"
                  onClick={(data) => {
                    // Recharts puts the original datum on `.payload`; fall back to
                    // the item itself since the data keys are spread onto it too.
                    const d = data as unknown as {
                      app_id?: number;
                      fullName?: string;
                      payload?: { app_id?: number; fullName?: string };
                    };
                    removeFromChart(d.payload ?? d);
                  }}
                >
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
              <span className="mr-3 inline-flex items-center gap-1">
                <span className="size-2.5 rounded-full bg-indigo-300" /> Tier 2
              </span>
              · Click a bar to remove that competitor permanently
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
            <CompetitorTable
              apps={tab === "tier1" ? tier1 : tier2}
              onRemove={(id) => removeCompetitor.mutate(id)}
              removingId={removeCompetitor.isPending ? removeCompetitor.variables : null}
            />
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
