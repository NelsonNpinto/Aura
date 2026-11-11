import { hashPassword } from "better-auth/crypto";
import type { Pool } from "pg";
import { purchasingDemoAccounts, PURCHASING_DEMO_ORG } from "../src/lib/purchasing-demo";

export async function seedPurchasingDemo(pool: Pool) {
  const accounts = await Promise.all(
    purchasingDemoAccounts.map(async (account) => ({
      ...account,
      hash: await hashPassword(account.password),
    })),
  );
  const client = await pool.connect();
  try {
    await client.query("BEGIN");
    await client.query(
      `INSERT INTO auth.organization (id, name, slug, "createdAt")
       VALUES ($1, 'AURA Purchasing Demo', $1, now()) ON CONFLICT (id) DO NOTHING`,
      [PURCHASING_DEMO_ORG],
    );
    for (const account of accounts) {
      await client.query(
        `INSERT INTO auth."user" (id, name, email, "emailVerified", "isAnonymous", "createdAt", "updatedAt")
         VALUES ($1, $2, $3, false, false, now(), now()) ON CONFLICT (id) DO NOTHING`,
        [account.id, `Demo ${account.label}`, account.email],
      );
      await client.query(
        `INSERT INTO auth.account (id, "accountId", "providerId", "userId", password, "createdAt", "updatedAt")
         VALUES ($1, $2, 'credential', $2, $3, now(), now()) ON CONFLICT (id) DO NOTHING`,
        [`${account.id}-credential`, account.id, account.hash],
      );
      await client.query(
        `INSERT INTO auth.member (id, "organizationId", "userId", role, "createdAt")
         VALUES ($1, $2, $3, $4, now()) ON CONFLICT (id) DO NOTHING`,
        [`${account.id}-member`, PURCHASING_DEMO_ORG, account.id, account.role],
      );
      await client.query(
        `INSERT INTO ap.procurement_members (org_id, user_id, role, vendor_id)
         VALUES ($1, $2, $3, $4) ON CONFLICT (org_id, user_id) DO NOTHING`,
        [PURCHASING_DEMO_ORG, account.id, account.role, account.role === "vendor" ? "ACME" : null],
      );
    }
    await client.query("COMMIT");
  } catch (error) {
    await client.query("ROLLBACK");
    throw error;
  } finally {
    client.release();
  }
}
