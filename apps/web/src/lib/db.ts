import "server-only";
import { Pool } from "pg";

declare global {
  var __auraPool: Pool | undefined;
}

/**
 * One pool per server instance; Neon's pooled URL does the real pooling.
 * Fluid compute serves many requests per instance, and a page load fans out into a burst of
 * RSC prefetches that each read the session. Three connections with a 5 s wait starved that
 * burst while Neon woke from scale-to-zero, and Better Auth logged "Could not validate the
 * database schema". Ten connections are cheap against the pooler; the longer wait covers a cold
 * start.
 */
export const pool: Pool =
  globalThis.__auraPool ??
  new Pool({
    connectionString: process.env.DATABASE_URL,
    max: 10,
    connectionTimeoutMillis: 10_000,
    idleTimeoutMillis: 10_000,
  });

// Neon closes idle connections; without a listener that error crashes the instance.
if (pool.listenerCount("error") === 0) {
  pool.on("error", (error) => {
    console.warn("pg pool idle client error:", error.message);
  });
}

if (process.env.NODE_ENV !== "production") globalThis.__auraPool = pool;
