"use client";

/** Sentiment — review sentiment breakdown, rating distribution, review browser. */

import { useMemo, useState } from "react";
import {
  Bar,
  BarChart,
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { usePageContext } from "@/lib/context";
import { useReviews, useSentiment } from "@/lib/hooks";
import { fmtDate } from "@/lib/format";
import {
  Badge,
  Card,
  EmptyState,
  MetricCard,
  PageTitle,
  SectionTitle,
  Select,
  Spinner,
} from "@/components/ui";

const SENTIMENT_COLORS = {
  Positive: "#16a34a",
  Negative: "#dc2626",
  Neutral: "#f59e0b",
};

// null = all time.
const PERIODS: { label: string; days: number | null }[] = [
  { label: "Last 30 days", days: 30 },
  { label: "Last 60 days", days: 60 },
  { label: "Last 90 days", days: 90 },
  { label: "All time", days: null },
];

function Methodology() {
  const [open, setOpen] = useState(false);
  return (
    <Card className="mb-6 py-3">
      <button
        onClick={() => setOpen(!open)}
        className="flex w-full items-center justify-between text-sm font-medium text-neutral-700"
      >
        ℹ️ How sentiment is scored
        <span className="text-neutral-400">{open ? "▲" : "▼"}</span>
      </button>
      {open && (
        <div className="mt-3 space-y-2 text-sm text-neutral-600">
          <p>
            Each review is labelled <b>Positive</b>, <b>Negative</b>, or <b>Neutral</b>{" "}
            using its star rating first, and AI only where the rating is ambiguous:
          </p>
          <ul className="list-disc space-y-1 pl-5">
            <li>
              <b>4–5 ★ → Positive</b> and <b>1–2 ★ → Negative</b> — assigned directly.
            </li>
            <li>
              <b>3 ★ (ambiguous)</b> → the review text decides: with AI on, a model
              reads it (it understands sarcasm and mixed-language reviews); with AI
              off, the rule-based VADER scorer is used.
            </li>
          </ul>
          <p className="text-xs text-neutral-400">
            “App Store rating” is the app’s official all-time average across{" "}
            <i>every</i> rating, including silent star-only taps that never appear as
            written reviews. The sentiment breakdown and “written-review avg” are based
            only on the recent <i>written</i> reviews Apple exposes (a small,
            recency-skewed sample). Apple does not publish recent star-only ratings, so
            the star-inclusive figure is necessarily all-time.
          </p>
        </div>
      )}
    </Card>
  );
}

function PeriodSelect({
  days,
  onChange,
}: {
  days: number | null;
  onChange: (days: number | null) => void;
}) {
  return (
    <Select
      className="w-40"
      value={days ?? "all"}
      onChange={(e) => {
        const v = e.target.value;
        onChange(v === "all" ? null : Number(v));
      }}
    >
      {PERIODS.map((p) => (
        <option key={p.label} value={p.days ?? "all"}>
          {p.label}
        </option>
      ))}
    </Select>
  );
}

export default function SentimentPage() {
  const { appId, country } = usePageContext();
  const [days, setDays] = useState<number | null>(30);
  const { data: sentiment, isLoading, isError } = useSentiment(appId, country, days);
  const { data: reviewsData } = useReviews(appId, country, days);
  const [filter, setFilter] = useState("all");
  const periodLabel = PERIODS.find((p) => p.days === days)?.label ?? "Last 30 days";

  // Newest reviews first (iTunes review_date is an ISO string, sorts lexically).
  const reviews = useMemo(() => {
    const list = reviewsData?.reviews ?? [];
    return [...list].sort((a, b) =>
      (b.review_date ?? "").localeCompare(a.review_date ?? "")
    );
  }, [reviewsData?.reviews]);

  const ratingDist = useMemo(() => {
    const counts = [5, 4, 3, 2, 1].map((stars) => ({
      label: `${stars} ★`,
      stars,
      count: reviews.filter((r) => r.rating === stars).length,
      fill: stars >= 4 ? "#16a34a" : stars === 3 ? "#f59e0b" : "#dc2626",
    }));
    return counts;
  }, [reviews]);

  const filtered = useMemo(
    () =>
      filter === "all"
        ? reviews
        : reviews.filter((r) => r.sentiment_label === filter),
    [reviews, filter]
  );

  if (isLoading) {
    return (
      <div className="flex justify-center py-24">
        <Spinner className="size-8" />
      </div>
    );
  }

  if (isError || !sentiment) {
    return (
      <div className="mx-auto max-w-6xl">
        <PageTitle title="Sentiment Analysis">
          <PeriodSelect days={days} onChange={setDays} />
        </PageTitle>
        <EmptyState>
          No sentiment data for the {periodLabel.toLowerCase()} — collect the app
          for it first, or try a longer time range above.
        </EmptyState>
      </div>
    );
  }

  const pieData = [
    { name: "Positive", value: sentiment.positive_count },
    { name: "Negative", value: sentiment.negative_count },
    { name: "Neutral", value: sentiment.neutral_count },
  ].filter((d) => d.value > 0);

  return (
    <div className="mx-auto max-w-6xl">
      <PageTitle title="💬 Sentiment Analysis">
        <PeriodSelect days={days} onChange={setDays} />
      </PageTitle>
      <Methodology />

      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <MetricCard
          label={`Reviews (${periodLabel.toLowerCase()})`}
          value={sentiment.total_reviews}
        />
        <MetricCard
          label="Positive"
          value={<span className="text-green-600">{sentiment.positive_pct}%</span>}
        />
        <MetricCard
          label="Negative"
          value={<span className="text-red-600">{sentiment.negative_pct}%</span>}
        />
        <MetricCard
          label="App Store rating"
          value={
            sentiment.store_avg_rating != null
              ? `${sentiment.store_avg_rating} ★`
              : `${sentiment.avg_rating} ★`
          }
          hint={
            sentiment.store_avg_rating != null
              ? `All ratings incl. star-only${
                  sentiment.store_rating_count != null
                    ? ` (${sentiment.store_rating_count.toLocaleString()})`
                    : ""
                } · written-review avg ${sentiment.avg_rating}★`
              : "Average of recent written reviews (store rating unavailable)"
          }
        />
      </div>

      <div className="mt-6 grid gap-6 lg:grid-cols-2">
        <Card>
          <SectionTitle>Sentiment breakdown</SectionTitle>
          <ResponsiveContainer width="100%" height={260}>
            <PieChart>
              <Pie
                data={pieData}
                dataKey="value"
                nameKey="name"
                innerRadius={60}
                outerRadius={95}
                paddingAngle={2}
              >
                {pieData.map((d) => (
                  <Cell
                    key={d.name}
                    fill={SENTIMENT_COLORS[d.name as keyof typeof SENTIMENT_COLORS]}
                  />
                ))}
              </Pie>
              <Tooltip />
            </PieChart>
          </ResponsiveContainer>
          <div className="mt-2 flex justify-center gap-4 text-xs text-neutral-500">
            {pieData.map((d) => (
              <span key={d.name} className="flex items-center gap-1.5">
                <span
                  className="size-2.5 rounded-full"
                  style={{
                    background:
                      SENTIMENT_COLORS[d.name as keyof typeof SENTIMENT_COLORS],
                  }}
                />
                {d.name} ({d.value})
              </span>
            ))}
          </div>
        </Card>

        <Card>
          <SectionTitle>Rating distribution</SectionTitle>
          <ResponsiveContainer width="100%" height={280}>
            <BarChart data={ratingDist} layout="vertical" margin={{ left: 8 }}>
              <XAxis type="number" allowDecimals={false} tickLine={false} />
              <YAxis
                type="category"
                dataKey="label"
                width={40}
                tickLine={false}
                axisLine={false}
              />
              <Tooltip />
              <Bar dataKey="count" radius={[0, 6, 6, 0]}>
                {ratingDist.map((d) => (
                  <Cell key={d.stars} fill={d.fill} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </Card>
      </div>

      {/* ── Reviews table ───────────────────────────────────────────── */}
      <Card className="mt-6">
        <div className="mb-3 flex items-center justify-between gap-3">
          <SectionTitle>Recent reviews</SectionTitle>
          <Select
            className="w-40"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
          >
            <option value="all">All sentiments</option>
            <option value="positive">Positive</option>
            <option value="negative">Negative</option>
            <option value="neutral">Neutral</option>
          </Select>
        </div>
        {filtered.length ? (
          <div className="max-h-[480px] overflow-y-auto">
            <table className="w-full text-sm">
              <thead className="sticky top-0 bg-white text-left text-xs uppercase tracking-wide text-neutral-400">
                <tr>
                  <th className="py-2 pr-3">Date</th>
                  <th className="py-2 pr-3">Rating</th>
                  <th className="py-2 pr-3">Sentiment</th>
                  <th className="py-2 pr-3">Review</th>
                  <th className="py-2">Author</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-neutral-100">
                {filtered.slice(0, 100).map((r) => (
                  <tr key={r.review_id} className="align-top">
                    <td className="whitespace-nowrap py-2.5 pr-3 text-neutral-500">
                      {fmtDate(r.review_date)}
                    </td>
                    <td className="whitespace-nowrap py-2.5 pr-3 font-medium text-amber-500">
                      {"★".repeat(r.rating ?? 0)}
                    </td>
                    <td className="py-2.5 pr-3">
                      <Badge
                        color={
                          r.sentiment_label === "positive"
                            ? "green"
                            : r.sentiment_label === "negative"
                              ? "red"
                              : "amber"
                        }
                      >
                        {r.sentiment_label ?? "—"}
                      </Badge>
                    </td>
                    <td className="max-w-xl py-2.5 pr-3 text-neutral-700">
                      {r.review_text}
                    </td>
                    <td className="whitespace-nowrap py-2.5 text-neutral-400">
                      {r.author}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <EmptyState>No reviews match this filter.</EmptyState>
        )}
      </Card>
    </div>
  );
}
