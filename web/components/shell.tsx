"use client";

/**
 * App shell: left sidebar navigation + top context bar.
 *
 * The active app and country live in the URL (/a/[appId]/...?country=xx), the
 * pattern used by tools like AppTweak/Sensor Tower — switching either updates
 * the URL so every page follows the same context and links stay shareable.
 */

import Link from "next/link";
import { useParams, usePathname, useRouter, useSearchParams } from "next/navigation";
import {
  BarChart3,
  Home,
  LayoutDashboard,
  MessageSquareText,
  Star,
  Trophy,
} from "lucide-react";
import { useApps } from "@/lib/hooks";
import { COUNTRIES, countryLabel } from "@/lib/countries";
import { cn, Select } from "@/components/ui";

const NAV = [
  { slug: "overview", label: "Overview", icon: LayoutDashboard },
  { slug: "sentiment", label: "Sentiment", icon: MessageSquareText },
  { slug: "rankings", label: "Rankings", icon: BarChart3 },
  { slug: "competitors", label: "Competitors", icon: Trophy },
  { slug: "recommendations", label: "Recommendations", icon: Star },
];

function useActiveContext() {
  const params = useParams<{ appId?: string }>();
  const searchParams = useSearchParams();
  const appId = params.appId ? Number(params.appId) : null;
  const country = searchParams.get("country") ?? undefined;
  return { appId, country };
}

export function Sidebar() {
  const pathname = usePathname();
  const { appId, country } = useActiveContext();
  const q = country ? `?country=${country}` : "";

  return (
    <aside className="flex w-56 shrink-0 flex-col border-r border-neutral-200 bg-white">
      <Link href="/" className="flex items-center gap-2 px-5 py-5">
        <span className="flex size-8 items-center justify-center rounded-lg bg-indigo-600 text-sm font-bold text-white">
          A
        </span>
        <span className="text-sm font-semibold text-neutral-900">
          ASO Intelligence
        </span>
      </Link>
      <nav className="flex flex-1 flex-col gap-1 px-3 pb-4">
        <Link
          href="/"
          className={cn(
            "flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium",
            pathname === "/"
              ? "bg-indigo-50 text-indigo-700"
              : "text-neutral-600 hover:bg-neutral-100"
          )}
        >
          <Home className="size-4" />
          Home
        </Link>
        <p className="mt-4 mb-1 px-3 text-xs font-semibold uppercase tracking-wide text-neutral-400">
          Analysis
        </p>
        {NAV.map(({ slug, label, icon: Icon }) => {
          const href = appId ? `/a/${appId}/${slug}${q}` : null;
          const active = pathname.includes(`/${slug}`);
          return href ? (
            <Link
              key={slug}
              href={href}
              className={cn(
                "flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium",
                active
                  ? "bg-indigo-50 text-indigo-700"
                  : "text-neutral-600 hover:bg-neutral-100"
              )}
            >
              <Icon className="size-4" />
              {label}
            </Link>
          ) : (
            <span
              key={slug}
              className="flex cursor-not-allowed items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium text-neutral-300"
              title="Select an app first"
            >
              <Icon className="size-4" />
              {label}
            </span>
          );
        })}
      </nav>
      <p className="px-5 pb-4 text-xs text-neutral-400">
        Powered by Apple public APIs + AI
      </p>
    </aside>
  );
}

export function Topbar() {
  const router = useRouter();
  const pathname = usePathname();
  const { appId, country } = useActiveContext();
  const { data } = useApps();
  const apps = data?.apps ?? [];
  const activeApp = apps.find((a) => a.app_id === appId);

  // Countries offered = the ones the active app actually has data for.
  const appCountries = activeApp?.countries ?? [];

  function navigate(nextAppId: number, nextCountry?: string) {
    const app = apps.find((a) => a.app_id === nextAppId);
    const c =
      nextCountry && app?.countries.includes(nextCountry)
        ? nextCountry
        : app?.countries[0];
    // Keep the current section when switching app/country, else overview.
    const section =
      NAV.find((n) => pathname.includes(`/${n.slug}`))?.slug ?? "overview";
    router.push(`/a/${nextAppId}/${section}${c ? `?country=${c}` : ""}`);
  }

  return (
    <header className="flex h-14 items-center gap-3 border-b border-neutral-200 bg-white px-6">
      <div className="flex items-center gap-2">
        <span className="text-xs font-medium text-neutral-400">App</span>
        <Select
          className="w-56"
          value={appId ?? ""}
          onChange={(e) => e.target.value && navigate(Number(e.target.value), country)}
        >
          <option value="" disabled>
            {apps.length ? "Select an app…" : "No apps collected yet"}
          </option>
          {apps.map((a) => (
            <option key={a.app_id} value={a.app_id}>
              {a.name}
            </option>
          ))}
        </Select>
      </div>
      {appId != null && appCountries.length > 0 && (
        <div className="flex items-center gap-2">
          <span className="text-xs font-medium text-neutral-400">Country</span>
          <Select
            className="w-44"
            value={country && appCountries.includes(country) ? country : appCountries[0]}
            onChange={(e) => navigate(appId, e.target.value)}
          >
            {appCountries.map((c) => (
              <option key={c} value={c}>
                {countryLabel(c)}
              </option>
            ))}
          </Select>
        </div>
      )}
      <div className="ml-auto text-xs text-neutral-400">
        {activeApp ? activeApp.category : ""}
      </div>
    </header>
  );
}

export { COUNTRIES };
