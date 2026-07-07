"use client";

import { useParams, useSearchParams } from "next/navigation";

/** Read the active (appId, country) analysis context from the URL. */
export function usePageContext() {
  const params = useParams<{ appId: string }>();
  const searchParams = useSearchParams();
  return {
    appId: Number(params.appId),
    country: searchParams.get("country") ?? undefined,
  };
}
