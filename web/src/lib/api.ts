// Thin fetch wrapper for the FastAPI service. All engine work happens there.

import { useAuth } from "./auth";

export const API_URL = (import.meta.env.VITE_API_URL as string | undefined) ?? "http://localhost:8000";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public detail: unknown,
  ) {
    super(message);
  }
}

function messageOf(detail: unknown, fallback: string): string {
  if (typeof detail === "string") return detail;
  if (detail && typeof detail === "object" && "message" in detail) return String(detail.message);
  if (Array.isArray(detail)) return detail.map((d) => d?.msg ?? String(d)).join("; ");
  return fallback;
}

export function unreachable(origin = window.location.origin): string {
  return `Couldn't reach the API at ${API_URL}. Check that the API is running, that VITE_API_URL ` +
    `points to it, and that its ALLOWED_ORIGINS includes ${origin}.`;
}

export type Api = <T>(path: string, init?: { method?: string; json?: unknown; form?: FormData }) => Promise<T>;

export function useApi(): Api {
  const { headers } = useAuth();
  return async <T,>(path: string, init: { method?: string; json?: unknown; form?: FormData } = {}) => {
    const h: Record<string, string> = { ...headers() };
    let body: BodyInit | undefined;
    if (init.json !== undefined) {
      h["Content-Type"] = "application/json";
      body = JSON.stringify(init.json);
    } else if (init.form) {
      body = init.form;
    }
    let res: Response;
    try {
      res = await fetch(`${API_URL}${path}`, { method: init.method ?? (body ? "POST" : "GET"), headers: h, body });
    } catch {
      // The browser hides the reason (network down, wrong URL, or a CORS refusal), so say
      // what to check instead of the bare "Failed to fetch".
      throw new ApiError(0, unreachable(), null);
    }
    const text = await res.text();
    let data;
    try {
      data = text ? JSON.parse(text) : null;
    } catch {
      // Typically VITE_API_URL pointing at this website: the rewrite serves index.html.
      throw new ApiError(res.status, `The API address ${API_URL} returned a web page instead of data. ` +
        "Check that VITE_API_URL is the API service's address, not this site's.", null);
    }
    if (!res.ok) {
      const detail = data?.detail ?? data;
      throw new ApiError(res.status, messageOf(detail, `Request failed (${res.status})`), detail);
    }
    return data as T;
  };
}
