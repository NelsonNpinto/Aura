/**
 * Creates/updates Better Auth tables in schema `auth` and ensures the shared `demo` org exists.
 * Run with the DIRECT (unpooled) URL: `npm run auth:migrate`.
 */
import { getMigrations } from "better-auth/db/migration";
import { Pool } from "pg";
import { buildAuthOptions } from "../src/lib/auth-options";
import { DEMO_ORG_ID } from "../src/lib/roles";

async function main() {
  const url = process.env.DATABASE_URL_UNPOOLED ?? process.env.DATABASE_URL;
  if (!url) throw new Error("DATABASE_URL_UNPOOLED or DATABASE_URL required");
  const pool = new Pool({ connectionString: url, max: 1 });
  try {
    const { toBeCreated, toBeAdded, runMigrations } = await getMigrations(buildAuthOptions(pool));
    console.log(
      JSON.stringify({
        create: toBeCreated.map((t) => t.table),
        add: toBeAdded.map((t) => `${t.table}(${Object.keys(t.fields).join(",")})`),
      }),
    );
    await runMigrations();
    await pool.query(
      `INSERT INTO auth.organization (id, name, slug, "createdAt")
       VALUES ($1, 'AURA public demo (synthetic data)', 'demo', now())
       ON CONFLICT (id) DO NOTHING`,
      [DEMO_ORG_ID],
    );
    console.log("auth migrations applied; demo org ensured");
  } finally {
    await pool.end();
  }
}

main().catch((e) => {
  console.error(e instanceof Error ? e.message : e);
  process.exit(1);
});
