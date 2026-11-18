"use client";

import { authClient } from "./auth-client";
import { getPersona } from "./persona";

let cached: { token: string; exp: number } | null = null;
let pendingToken: Promise<string> | undefined;

function expOf(token: string): number {
  try {
    const payload = JSON.parse(
      atob(token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/")),
    );
    return typeof payload.exp === "number" ? payload.exp : 0;
  } catch {
    return 0;
  }
}

export async function apiToken(force = false): Promise<string> {
  const now = Date.now() / 1000;
  if (!force && cached && cached.exp - 60 > now) return cached.token;
  if (pendingToken) return pendingToken;
  const request = authClient.token().then((res) => {
    if (pendingToken !== request) {
      throw new DOMException("The active account changed.", "AbortError");
    }
    const token = res.data?.token;
    if (!token)
      throw new ApiError(
        401,
        "unauthorized",
        res.error?.message ?? "Sign in to continue",
      );
    cached = { token, exp: expOf(token) };
    return token;
  });
  pendingToken = request;
  try {
    return await request;
  } finally {
    if (pendingToken === request) pendingToken = undefined;
  }
}

export function clearApiToken() {
  cached = null;
  pendingToken = undefined;
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

export async function apiResponse(
  path: string,
  init: RequestInit = {},
  origin = "",
): Promise<Response> {
  const headers = new Headers(init.headers);
  if (
    init.body &&
    !(init.body instanceof FormData) &&
    !headers.has("content-type")
  ) {
    headers.set("content-type", "application/json");
  }
  headers.set("x-aura-persona", getPersona());
  const send = (token: string) => {
    headers.set("authorization", `Bearer ${token}`);
    return fetch(`${origin}/api/v1${path}`, {
      cache: "no-store",
      ...init,
      headers,
    });
  };
  const token = await apiToken();
  let res = await send(token);
  if (res.status === 401) {
    if (cached?.token === token) cached = null;
    res = await send(await apiToken());
  }
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    const e = body?.error ?? {};
    const retryAfter = res.headers.get("retry-after");
    const msg =
      res.status === 429 && retryAfter
        ? `${e.message ?? "Too many requests"}. Retry in ${retryAfter}s.`
        : (e.message ??
          (res.status === 413
            ? "The document is too large to upload."
            : `Request failed (${res.status})`));
    throw new ApiError(
      res.status,
      e.code ?? "error",
      msg,
      e.details,
      res.headers.get("x-request-id"),
    );
  }
  return res;
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await apiResponse(path, init);
  return res.status === 204 ? (undefined as T) : (res.json() as Promise<T>);
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
  // In local dev the Next.js proxy buffers streamed responses, so SSE goes straight to the API
  // (CORS allows the web origin). In production web and api share one origin on Vercel.
  const origin = process.env.NEXT_PUBLIC_AURA_STREAM_ORIGIN ?? "";
  const headers = new Headers(init.headers);
  headers.set("accept", "text/event-stream");
  const res = await apiResponse(
    path,
    {
      ...init,
      signal: signal ?? init.signal,
      headers,
    },
    origin,
  );
  if (
    !res.body ||
    !res.headers.get("content-type")?.startsWith("text/event-stream")
  ) {
    throw new Error("The server did not return a live response.");
  }
  const reader = res.body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let separator: RegExpExecArray | null;
      while ((separator = /\r?\n\r?\n/.exec(buf))) {
        const block = buf.slice(0, separator.index);
        buf = buf.slice(separator.index + separator[0].length);
        let type = "message";
        const data: string[] = [];
        for (const line of block.split(/\r?\n/)) {
          if (line.startsWith("event:")) type = line.slice(6).trimStart();
          else if (line.startsWith("data:"))
            data.push(line.slice(5).trimStart());
        }
        if (data.length) onEvent(type, JSON.parse(data.join("\n")));
      }
    }
  } finally {
    reader.releaseLock();
  }
}

export function money(
  minor: number | null | undefined,
  currency?: string | null,
): string {
  if (minor === null || minor === undefined) return "—";
  try {
    return new Intl.NumberFormat("en-US", {
      style: "currency",
      currency: currency || "USD",
    }).format(minor / 100);
  } catch {
    return `${(minor / 100).toFixed(2)} ${currency ?? ""}`;
  }
}
