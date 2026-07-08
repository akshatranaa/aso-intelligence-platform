/** Thin fetch wrapper for the same-origin /api proxy. */

export class ApiError extends Error {
  status: number;
  constructor(status: number, detail: string) {
    super(detail);
    this.status = status;
  }
}

async function request<T>(
  method: "GET" | "POST" | "DELETE",
  path: string,
  params?: Record<string, string | number | boolean | undefined>
): Promise<T> {
  const url = new URL(`/api${path}`, window.location.origin);
  if (params) {
    for (const [k, v] of Object.entries(params)) {
      if (v !== undefined && v !== null) url.searchParams.set(k, String(v));
    }
  }
  const res = await fetch(url, { method });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new ApiError(res.status, body?.detail ?? `API error ${res.status}`);
  }
  return body as T;
}

export const apiGet = <T>(
  path: string,
  params?: Record<string, string | number | boolean | undefined>
) => request<T>("GET", path, params);

export const apiPost = <T>(
  path: string,
  params?: Record<string, string | number | boolean | undefined>
) => request<T>("POST", path, params);

export const apiDelete = <T>(
  path: string,
  params?: Record<string, string | number | boolean | undefined>
) => request<T>("DELETE", path, params);
