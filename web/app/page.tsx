"use client";

/** Home — collect a new app or open an already-collected one. */

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import { ChevronRight, Loader2, Search } from "lucide-react";
import { apiPost } from "@/lib/api";
import { useApps, useCollectJob } from "@/lib/hooks";
import { COUNTRIES, countryLabel } from "@/lib/countries";
import type { CollectStart } from "@/lib/types";
import {
  Badge,
  Button,
  Card,
  CheckboxRow,
  EmptyState,
  Input,
  PageTitle,
  SectionTitle,
  Select,
  Spinner,
} from "@/components/ui";

export default function HomePage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const { data: appsData, isLoading: appsLoading } = useApps();

  const [name, setName] = useState("");
  const [country, setCountry] = useState("in");
  const [useLlm, setUseLlm] = useState(true);
  const [force, setForce] = useState(false);
  const [jobId, setJobId] = useState<string | null>(null);
  const [startError, setStartError] = useState<string | null>(null);
  const [elapsed, setElapsed] = useState(0);

  const { data: job } = useCollectJob(jobId);
  const running = jobId != null && (!job || job.status === "running");

  async function startCollect() {
    if (!name.trim()) return;
    setStartError(null);
    setElapsed(0);
    try {
      const start = await apiPost<CollectStart>(
        `/collect/${encodeURIComponent(name.trim())}`,
        { use_llm: useLlm, country, force }
      );
      setJobId(start.job_id);
      // Lightweight elapsed counter for the progress card.
      const t = setInterval(() => setElapsed((e) => e + 1), 1000);
      const stop = setInterval(() => {
        const j = queryClient.getQueryData<{ status: string }>([
          "collect-job",
          start.job_id,
        ]);
        if (j && j.status !== "running") {
          clearInterval(t);
          clearInterval(stop);
          queryClient.invalidateQueries({ queryKey: ["apps"] });
        }
      }, 1000);
    } catch (e) {
      setStartError(e instanceof Error ? e.message : "Failed to start collection");
    }
  }

  const done = job?.status === "done" ? job.result : null;
  const failed = job?.status === "error" ? (job.detail ?? "Unknown error") : null;

  return (
    <div className="mx-auto max-w-5xl">
      <PageTitle
        title="ASO Intelligence Platform"
        subtitle="Collect an app from any App Store and analyse its keywords, sentiment, and competitors."
      />

      <div className="grid gap-6 lg:grid-cols-5">
        {/* ── Collect ─────────────────────────────────────────────────── */}
        <Card className="lg:col-span-3">
          <SectionTitle>🔍 Collect an app</SectionTitle>
          <div className="space-y-4">
            <div>
              <label className="mb-1 block text-xs font-medium text-neutral-500">
                App name
              </label>
              <Input
                placeholder="e.g. Spotify"
                value={name}
                onChange={(e) => setName(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && !running && startCollect()}
                disabled={running}
              />
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-neutral-500">
                App Store country
              </label>
              <Select
                value={country}
                onChange={(e) => setCountry(e.target.value)}
                disabled={running}
              >
                {COUNTRIES.map((c) => (
                  <option key={c.code} value={c.code}>
                    {c.flag} {c.label}
                  </option>
                ))}
              </Select>
            </div>
            <CheckboxRow
              label="Use AI during analysis"
              help="Smarter seeds, competitor judging, and review analysis (uses API credits)."
              checked={useLlm}
              onChange={setUseLlm}
            />
            <CheckboxRow
              label="Re-discover competitors"
              help="Ignore the 7-day cache and re-run competitor discovery from scratch."
              checked={force}
              onChange={setForce}
            />
            <Button
              onClick={startCollect}
              disabled={running || !name.trim()}
              className="w-full"
            >
              {running ? <Loader2 className="size-4 animate-spin" /> : <Search className="size-4" />}
              {running ? "Collecting…" : "Collect"}
            </Button>

            {running && (
              <div className="rounded-lg border border-indigo-100 bg-indigo-50 p-4 text-sm text-indigo-800">
                <p className="flex items-center gap-2 font-medium">
                  <Spinner /> Collecting “{name.trim()}” for {countryLabel(country)}…
                </p>
                <p className="mt-1 text-xs text-indigo-600">
                  Full pipeline (metadata, competitors, reviews, rankings) — takes a
                  few minutes due to Apple API rate limits. {elapsed}s elapsed.
                </p>
              </div>
            )}
            {startError && (
              <p className="rounded-lg bg-red-50 p-3 text-sm text-red-700">{startError}</p>
            )}
            {failed && (
              <p className="rounded-lg bg-red-50 p-3 text-sm text-red-700">
                Collection failed: {failed}
              </p>
            )}
            {done && (
              <div className="rounded-lg border border-green-200 bg-green-50 p-4 text-sm">
                <p className="font-medium text-green-800">
                  ✅ Collected {done.app_name} ({countryLabel(done.country)})
                </p>
                <p className="mt-1 text-xs text-green-700">
                  {done.reviews_saved} new reviews · {done.keywords_tracked} keywords tracked
                </p>
                {done.seed_warning && (
                  <p className="mt-2 rounded bg-amber-50 p-2 text-xs text-amber-700">
                    ⚠️ {done.seed_warning}
                  </p>
                )}
                <Button
                  className="mt-3"
                  onClick={() =>
                    router.push(`/a/${done.app_id}/overview?country=${done.country}`)
                  }
                >
                  View analysis <ChevronRight className="size-4" />
                </Button>
              </div>
            )}
          </div>
        </Card>

        {/* ── Collected apps ──────────────────────────────────────────── */}
        <Card className="lg:col-span-2">
          <SectionTitle>📂 Your apps</SectionTitle>
          {appsLoading ? (
            <div className="flex justify-center py-8">
              <Spinner className="size-6" />
            </div>
          ) : !appsData?.apps.length ? (
            <EmptyState>No apps collected yet — collect your first one.</EmptyState>
          ) : (
            <ul className="divide-y divide-neutral-100">
              {appsData.apps.map((a) => (
                <li key={a.app_id}>
                  <button
                    onClick={() =>
                      router.push(
                        `/a/${a.app_id}/overview${
                          a.countries[0] ? `?country=${a.countries[0]}` : ""
                        }`
                      )
                    }
                    className="flex w-full items-center justify-between gap-2 rounded-lg px-2 py-2.5 text-left hover:bg-neutral-50"
                  >
                    <span className="min-w-0">
                      <span className="block truncate text-sm font-medium text-neutral-900">
                        {a.name}
                      </span>
                      <span className="block text-xs text-neutral-400">
                        {a.category ?? "—"}
                      </span>
                    </span>
                    <span className="flex shrink-0 items-center gap-1">
                      {a.countries.map((c) => (
                        <Badge key={c} color="indigo">
                          {c.toUpperCase()}
                        </Badge>
                      ))}
                      <ChevronRight className="size-4 text-neutral-300" />
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </div>
  );
}
