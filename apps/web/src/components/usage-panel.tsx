"use client";

import { useQuery } from "@tanstack/react-query";
import { Card, ErrorNote, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";

type Bucket = { used: number; limit: number; remaining: number };
type Usage = {
  day_utc: string;
  resets_in_s: number;
  global: Bucket;
  org: Bucket;
  user: Bucket;
  providers: Record<string, { requests_today: number; rpd_limit: number }>;
  source: string;
};

export function UsagePanel() {
  const q = useQuery({ queryKey: ["usage"], queryFn: () => api<Usage>("/usage"), refetchInterval: 30_000 });
  return (
    <Card>
      <h2 className="font-semibold">Remaining demo budget</h2>
      {q.isPending && <Skeleton className="mt-3 h-16" />}
      <ErrorNote error={q.error} />
      {q.data && (
        <>
          <div className="mt-3 grid grid-cols-3 gap-4">
            {(["user", "org", "global"] as const).map((k) => (
              <div key={k}>
                <div className="text-xs uppercase text-muted">{k}</div>
                <div className="text-xl font-semibold">{q.data[k].remaining}<span className="text-sm text-muted"> / {q.data[k].limit}</span></div>
              </div>
            ))}
          </div>
          <details className="mt-3 text-sm">
            <summary className="cursor-pointer text-muted">Provider requests today</summary>
            <ul className="mt-2 space-y-1 font-mono text-xs">
              {Object.entries(q.data.providers).map(([m, v]) => (
                <li key={m}>{m}: {v.requests_today} / {v.rpd_limit}</li>
              ))}
            </ul>
          </details>
          <p className="mt-2 text-xs text-muted">
            Resets in {Math.round(q.data.resets_in_s / 3600)} h (UTC midnight) · source: {q.data.source}
          </p>
        </>
      )}
    </Card>
  );
}
