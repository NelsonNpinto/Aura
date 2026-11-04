"use client";

import { authClient } from "./auth-client";

let cached: { token: string; exp: number } | null = null;

function expOf(token: string): number {
  try {
    const payload = JSON.parse(atob(token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/")));
    return typeof payload.exp === "number" ? payload.exp : 0;
  } catch {
    return 0;
  }
}

export async function apiToken(force = false): Promise<string> {
  const now = Date.now() / 1000;
  if (!force && cached && cached.exp - 60 > now) return cached.token;
  const res = await authClient.token();
  const token = res.data?.token;
  if (!token) throw new ApiError(401, "unauthorized", "Not signed in");
  cached = { token, exp: expOf(token) };
  return token;
}

export function clearApiToken() {
  cached = null;
}

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public details?: unknown,
    public requestId?: string | null,
  ) {
    super(message);
  }
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const send = async (token: string) =>
    fetch(`/api/v1${path}`, {
      ...init,
      headers: {
        ...(init.body && !(init.body instanceof FormData) ? { "content-type": "application/json" } : {}),
        ...init.headers,
        authorization: `Bearer ${token}`,
      },
    });
  let res = await send(await apiToken());
  if (res.status === 401) res = await send(await apiToken(true));
  if (res.status === 204) return undefined as T;
  const body = await res.json().catch(() => null);
  if (!res.ok) {
    const e = body?.error ?? {};
    const msg = e.code === "budget_exhausted" || e.code === "rate_limited"
      ? `${e.message} (retry in ${res.headers.get("retry-after") ?? "?"}s)`
      : e.message ?? `Request failed (${res.status})`;
    throw new ApiError(res.status, e.code ?? "error", msg, e.details, res.headers.get("x-request-id"));
  }
  return body as T;
}
