import assert from "node:assert/strict";
import { betterAuth } from "better-auth";
import { Pool } from "pg";
import { buildAuthOptions } from "../src/lib/auth-options";
import { purchasingDemoAccounts, PURCHASING_DEMO_ORG } from "../src/lib/purchasing-demo";
import { seedPurchasingDemo } from "./seed-purchasing-demo";

async function main() {
  if (process.env.APP_ENV !== "test" || !process.env.DATABASE_URL) {
    throw new Error("A test database is required");
  }
  const pool = new Pool({ connectionString: process.env.DATABASE_URL });
  try {
    await seedPurchasingDemo(pool);
    await seedPurchasingDemo(pool);
    const auth = betterAuth(buildAuthOptions(pool));
    for (const account of purchasingDemoAccounts) {
      const { user } = await auth.api.signInEmail({ body: { email: account.email, password: account.password } });
      assert.equal(user.id, account.id);
      const membership = await pool.query(
        `SELECT m.role, p.role AS "purchasingRole", p.vendor_id FROM auth.member m
         JOIN ap.procurement_members p ON p.org_id = m."organizationId" AND p.user_id = m."userId"
         WHERE m."organizationId" = $1 AND m."userId" = $2`,
        [PURCHASING_DEMO_ORG, user.id],
      );
      assert.deepEqual(membership.rows, [{
        role: account.role,
        purchasingRole: account.role,
        vendor_id: account.role === "vendor" ? "ACME" : null,
      }]);
    }
    console.log("All four demo accounts signed in with the expected Purchasing role");
  } finally {
    await pool.end();
  }
}

main().catch((error) => {
  console.error(error instanceof Error ? error.message : error);
  process.exitCode = 1;
});
