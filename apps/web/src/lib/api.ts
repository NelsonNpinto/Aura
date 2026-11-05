"use client";

import { authClient } from "./auth-client";
import { getPersona } from "./persona";

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
        "x-aura-persona": getPersona(),
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

export type RunEvent = {
  run_id: string;
  seq: number;
  ts: string;
  type: string;
  node: string | null;
  payload: Record<string, unknown>;
};

/** POST/GET an SSE endpoint with auth (EventSource cannot send headers) and parse events. */
export async function streamEvents(
  path: string,
  init: RequestInit,
  onEvent: (type: string, data: Record<string, unknown>) => void,
  signal?: AbortSignal,
): Promise<void> {
  const token = await apiToken();
  // In local dev the Next.js proxy buffers streamed responses, so SSE goes straight to the API
  // (CORS allows the web origin). In production web and api share one origin on Vercel.
  const origin = process.env.NEXT_PUBLIC_AURA_STREAM_ORIGIN ?? "";
  const res = await fetch(`${origin}/api/v1${path}`, {
    ...init,
    signal,
    headers: {
      ...(init.body ? { "content-type": "application/json" } : {}),
      "x-aura-persona": getPersona(),
      ...init.headers,
      authorization: `Bearer ${token}`,
      accept: "text/event-stream",
    },
  });
  if (!res.ok || !res.body) {
    const body = await res.json().catch(() => null);
    const e = body?.error ?? {};
    throw new ApiError(res.status, e.code ?? "error", e.message ?? `Request failed (${res.status})`, e.details);
  }
  const reader = res.body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let i: number;
    while ((i = buf.indexOf("\n\n")) >= 0) {
      const block = buf.slice(0, i);
      buf = buf.slice(i + 2);
      let type = "message";
      const data: string[] = [];
      for (const line of block.split("\n")) {
        if (line.startsWith("event: ")) type = line.slice(7);
        else if (line.startsWith("data: ")) data.push(line.slice(6));
      }
      if (data.length) {
        try {
          onEvent(type, JSON.parse(data.join("\n")));
        } catch {}
      }
    }
  }
}

export function money(minor: number | null | undefined, currency?: string | null): string {
  if (minor === null || minor === undefined) return "—";
  try {
    return new Intl.NumberFormat("en-US", { style: "currency", currency: currency || "USD" }).format(minor / 100);
  } catch {
    return `${(minor / 100).toFixed(2)} ${currency ?? ""}`;
  }
}
