"use client";

/** Home — collect a new app or open an already-collected one. */

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ChevronRight, Loader2, Search, X } from "lucide-react";
import { apiGet, apiPost } from "@/lib/api";
import { useApps, useCollectJob } from "@/lib/hooks";
import { COUNTRIES, countryLabel } from "@/lib/countries";
import { requestNotifyPermission, useJobTabNotifier } from "@/lib/use-job-tab-notifier";
import type { AppSearchResult, CollectStart } from "@/lib/types";
import {
  Button,
  Card,
  CheckboxRow,
  cn,
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

  const [country, setCountry] = useState("in");
  const [name, setName] = useState("");
  const [useLlm, setUseLlm] = useState(true);
  const [force, setForce] = useState(false);
  const [jobId, setJobId] = useState<string | null>(null);
  const [startError, setStartError] = useState<string | null>(null);
  const [elapsed, setElapsed] = useState(0);

  // ── Load a saved app (select app + country, then open) ──────────────────
  const [loadAppId, setLoadAppId] = useState<number | null>(null);
  const [loadCountry, setLoadCountry] = useState("");

  // ── App-name autocomplete ──────────────────────────────────────────────
  const [suggestions, setSuggestions] = useState<AppSearchResult[]>([]);
  const [showSuggestions, setShowSuggestions] = useState(false);
  // The exact app picked from autocomplete — collect this ID rather than
  // re-searching the name (whose top hit can be a different app).
  const [selectedAppId, setSelectedAppId] = useState<number | null>(null);
  const skipSearch = useRef(false); // don't re-search right after picking

  useEffect(() => {
    if (skipSearch.current) {
      skipSearch.current = false;
      return;
    }
    const term = name.trim();
    if (term.length < 2) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setSuggestions([]);
      return;
    }
    const t = setTimeout(async () => {
      try {
        const r = await apiGet<{ results: AppSearchResult[] }>("/search", {
          term,
          country,
        });
        setSuggestions(r.results);
        setShowSuggestions(true);
      } catch {
        /* ignore search errors */
      }
    }, 300);
    return () => clearTimeout(t);
  }, [name, country]);

  function pickSuggestion(s: AppSearchResult) {
    skipSearch.current = true;
    setName(s.name);
    setSelectedAppId(s.app_id);
    setShowSuggestions(false);
  }

  const { data: job } = useCollectJob(jobId);
  const running = jobId != null && (!job || job.status === "running");

  // Reflects job progress in the tab (animated favicon; checkmark/error +
  // notification if the user switches away while it's running).
  useJobTabNotifier(jobId ? job?.status : undefined, `Collected ${name.trim()}`);

  async function startCollect() {
    if (!name.trim()) return;
    setShowSuggestions(false);
    setStartError(null);
    setElapsed(0);
    requestNotifyPermission(); // ask now, while we have a user gesture
    try {
      const start = await apiPost<CollectStart>(
        `/collect/${encodeURIComponent(name.trim())}`,
        { use_llm: useLlm, country, force, app_id: selectedAppId ?? undefined }
      );
      setJobId(start.job_id);
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

  const untrack = useMutation({
    mutationFn: (appId: number) => apiPost(`/app/${appId}/untrack`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["apps"] }),
  });

  const done = job?.status === "done" ? job.result : null;
  const failed = job?.status === "error" ? (job.detail ?? "Unknown error") : null;

  // Selected saved app + its countries, derived (falls back to the first app so
  // the form is always populated once apps load).
  const apps = appsData?.apps ?? [];
  const selectedApp = apps.find((a) => a.app_id === loadAppId) ?? apps[0];
  const loadCountries = selectedApp?.countries ?? [];
  const effectiveCountry = loadCountries.includes(loadCountry)
    ? loadCountry
    : (loadCountries[0] ?? "");

  function loadApp() {
    if (!selectedApp) return;
    router.push(
      `/a/${selectedApp.app_id}/overview${
        effectiveCountry ? `?country=${effectiveCountry}` : ""
      }`
    );
  }

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

            <div className="relative">
              <label className="mb-1 block text-xs font-medium text-neutral-500">
                App name
              </label>
              <Input
                placeholder="Start typing — e.g. Spotify"
                value={name}
                onChange={(e) => {
                  setName(e.target.value);
                  setSelectedAppId(null); // typing again = search by name, not the old pick
                }}
                onFocus={() => suggestions.length && setShowSuggestions(true)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !running) {
                    setShowSuggestions(false);
                    startCollect();
                  }
                  if (e.key === "Escape") setShowSuggestions(false);
                }}
                disabled={running}
                autoComplete="off"
              />
              {showSuggestions && suggestions.length > 0 && (
                <ul className="absolute z-20 mt-1 max-h-72 w-full overflow-y-auto rounded-lg border border-neutral-200 bg-white shadow-lg">
                  {suggestions.map((s) => (
                    <li key={s.app_id}>
                      <button
                        type="button"
                        onClick={() => pickSuggestion(s)}
                        className="flex w-full items-center gap-3 px-3 py-2 text-left hover:bg-neutral-50"
                      >
                        {s.artwork && (
                          // eslint-disable-next-line @next/next/no-img-element
                          <img
                            src={s.artwork}
                            alt=""
                            className="size-8 shrink-0 rounded-lg"
                          />
                        )}
                        <span className="min-w-0">
                          <span className="block truncate text-sm font-medium text-neutral-800">
                            {s.name}
                          </span>
                          <span className="block truncate text-xs text-neutral-400">
                            {s.category ?? ""}
                            {s.seller ? ` · ${s.seller}` : ""}
                          </span>
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
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

                <div className="mt-3 flex items-center gap-1.5">
                  {Array.from(
                    { length: job?.step_total ?? 5 },
                    (_, i) => i + 1
                  ).map((i) => (
                    <span
                      key={i}
                      className={cn(
                        "h-1.5 flex-1 rounded-full transition-colors duration-500",
                        job?.step_index && i <= job.step_index
                          ? "bg-indigo-500"
                          : "bg-indigo-100"
                      )}
                    />
                  ))}
                </div>
                <p className="mt-2 text-xs font-medium text-indigo-700">
                  {job?.step ?? "Starting…"}
                  {job?.step_index && job?.step_total
                    ? ` (${job.step_index}/${job.step_total})`
                    : ""}
                </p>

                <p className="mt-2 text-xs text-indigo-600">
                  Takes a few minutes due to Apple API rate limits — feel free to
                  switch tabs, we’ll flag the tab and notify you when it’s done.{" "}
                  {elapsed}s elapsed.
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
                {done.reviews_warning && (
                  <p className="mt-2 rounded bg-red-50 p-2 text-xs text-red-700">
                    ⚠️ {done.reviews_warning}
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

        {/* ── Load a saved app ────────────────────────────────────────── */}
        <Card className="lg:col-span-2">
          <SectionTitle>📂 Load a saved app</SectionTitle>
          {appsLoading ? (
            <div className="flex justify-center py-8">
              <Spinner className="size-6" />
            </div>
          ) : !apps.length ? (
            <EmptyState>No apps collected yet — collect your first one.</EmptyState>
          ) : (
            <div className="space-y-4">
              <div>
                <label className="mb-1 block text-xs font-medium text-neutral-500">
                  App
                </label>
                <Select
                  value={selectedApp?.app_id ?? ""}
                  onChange={(e) => {
                    setLoadAppId(Number(e.target.value));
                    setLoadCountry(""); // reset — pick the new app's first country
                  }}
                >
                  {apps.map((a) => (
                    <option key={a.app_id} value={a.app_id}>
                      {a.name}
                    </option>
                  ))}
                </Select>
              </div>

              <div>
                <label className="mb-1 block text-xs font-medium text-neutral-500">
                  Country
                </label>
                <Select
                  value={effectiveCountry}
                  onChange={(e) => setLoadCountry(e.target.value)}
                  disabled={loadCountries.length === 0}
                >
                  {loadCountries.map((c) => (
                    <option key={c} value={c}>
                      {countryLabel(c)}
                    </option>
                  ))}
                </Select>
                <p className="mt-1 text-xs text-neutral-400">
                  Only the countries this app has been collected for.
                </p>
              </div>

              <Button onClick={loadApp} disabled={!selectedApp} className="w-full">
                Load analysis <ChevronRight className="size-4" />
              </Button>

              <button
                onClick={() => {
                  if (!selectedApp) return;
                  if (
                    window.confirm(
                      `Are you sure you want to remove "${selectedApp.name}"?\n\n` +
                        "It will disappear from your saved apps. Its collected " +
                        "data is kept — re-collect it any time to bring it back."
                    )
                  ) {
                    untrack.mutate(selectedApp.app_id);
                    setLoadAppId(null);
                  }
                }}
                disabled={!selectedApp || untrack.isPending}
                className="flex w-full items-center justify-center gap-1.5 rounded-lg py-1.5 text-xs text-neutral-400 hover:text-red-500"
              >
                <X className="size-3.5" /> Remove this app from the list
              </button>
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}
