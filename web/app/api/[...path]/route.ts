/**
 * Server-side proxy to the FastAPI backend.
 *
 * The browser only ever calls same-origin /api/* — this handler forwards the
 * request to ASO_API_BASE and attaches the X-API-Key header from a
 * server-only env var, so the key is never exposed to the client and CORS
 * never comes into play.
 */
import { NextRequest, NextResponse } from "next/server";

const API_BASE = process.env.ASO_API_BASE ?? "http://localhost:8000";
const API_KEY = process.env.ASO_API_KEY;

async function proxy(
  req: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
): Promise<NextResponse> {
  const { path } = await params;
  const url = new URL(`${API_BASE}/${path.join("/")}`);
  req.nextUrl.searchParams.forEach((value, key) => {
    url.searchParams.set(key, value);
  });

  const headers: Record<string, string> = {};
  if (API_KEY) headers["X-API-Key"] = API_KEY;

  try {
    const upstream = await fetch(url, {
      method: req.method,
      headers,
      // Collect kicks off a background job and returns fast, but a Render
      // cold start can take ~60s — keep a generous timeout.
      signal: AbortSignal.timeout(120_000),
      cache: "no-store",
    });
    const body = await upstream.text();
    return new NextResponse(body, {
      status: upstream.status,
      headers: { "Content-Type": "application/json" },
    });
  } catch (err) {
    const detail =
      err instanceof Error && err.name === "TimeoutError"
        ? "Backend timed out (it may be cold-starting — try again in a minute)"
        : "Could not reach the backend API";
    return NextResponse.json({ detail }, { status: 502 });
  }
}

export { proxy as GET, proxy as POST, proxy as PUT, proxy as DELETE };
