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
    const res = await fetch(`${API_URL}${path}`, { method: init.method ?? (body ? "POST" : "GET"), headers: h, body });
    const text = await res.text();
    const data = text ? JSON.parse(text) : null;
    if (!res.ok) {
      const detail = data?.detail ?? data;
      throw new ApiError(res.status, messageOf(detail, `Request failed (${res.status})`), detail);
    }
    return data as T;
  };
}
