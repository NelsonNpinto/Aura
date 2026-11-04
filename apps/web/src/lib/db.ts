import "server-only";
import { Pool } from "pg";

declare global {
  var __auraPool: Pool | undefined;
}

/** One small pool per server instance. Neon's pooled URL does the real pooling. */
export const pool: Pool =
  globalThis.__auraPool ??
  new Pool({
    connectionString: process.env.DATABASE_URL,
    max: 3,
    idleTimeoutMillis: 10_000,
  });

if (process.env.NODE_ENV !== "production") globalThis.__auraPool = pool;
