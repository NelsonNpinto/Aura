import type { BetterAuthOptions } from "better-auth";
import { anonymous, captcha, jwt, organization } from "better-auth/plugins";
import { createAccessControl } from "better-auth/plugins/access";
import { defaultStatements } from "better-auth/plugins/organization/access";
import { Kysely, PostgresDialect } from "kysely";
import type { Pool } from "pg";
import { DEMO_ORG_ID, parseRoles } from "./roles";

const ac = createAccessControl({ ...defaultStatements });
const none = ac.newRole({ organization: [], member: [], invitation: [] });
const orgAdmin = ac.newRole({
  organization: ["update"],
  member: ["create", "update", "delete"],
  invitation: ["create", "cancel"],
});

export function buildAuthOptions(pool: Pool): BetterAuthOptions {
  const baseURL = process.env.BETTER_AUTH_URL ?? "http://localhost:3000";
  const turnstileSecret = process.env.TURNSTILE_SECRET_KEY;

  /** Active org membership, falling back to the user's first membership (the session can be
   *  created before the sign-up hook has inserted it). */
  async function membership(userId: string, orgId: string | null | undefined) {
    const r = await pool.query<{ organizationId: string; role: string }>(
      `SELECT "organizationId", role FROM auth.member WHERE "userId" = $1
       ORDER BY ("organizationId" = $2) DESC NULLS LAST, "createdAt" LIMIT 1`,
      [userId, orgId ?? null],
    );
    const row = r.rows[0];
    return row ? { orgId: row.organizationId, roles: parseRoles(row.role) } : { orgId: null, roles: [] };
  }

  return {
    appName: "AURA",
    baseURL,
    secret: process.env.BETTER_AUTH_SECRET,
    database: {
      dialect: new PostgresDialect({ pool }),
      type: "postgres",
      schemaName: "auth",
    },
    emailAndPassword: { enabled: true, minPasswordLength: 10, autoSignIn: true },
    socialProviders:
      process.env.GITHUB_CLIENT_ID && process.env.GITHUB_CLIENT_SECRET
        ? {
            github: {
              clientId: process.env.GITHUB_CLIENT_ID,
              clientSecret: process.env.GITHUB_CLIENT_SECRET,
            },
          }
        : {},
    session: { expiresIn: 60 * 60 * 24 * 7, updateAge: 60 * 60 * 24 },
    advanced: { useSecureCookies: baseURL.startsWith("https://") },
    databaseHooks: {
      user: {
        create: {
          // Guests join the shared synthetic `demo` org; registered users get a personal org.
          after: async (user) => {
            const isAnon = Boolean((user as { isAnonymous?: boolean }).isAnonymous);
            const now = new Date();
            if (isAnon) {
              await pool.query(
                'INSERT INTO auth.member (id, "organizationId", "userId", role, "createdAt") VALUES ($1,$2,$3,$4,$5)',
                [crypto.randomUUID(), DEMO_ORG_ID, user.id, "guest", now],
              );
              return;
            }
            const orgId = crypto.randomUUID();
            const slug = `org-${orgId.slice(0, 8)}`;
            await pool.query(
              'INSERT INTO auth.organization (id, name, slug, "createdAt") VALUES ($1,$2,$3,$4)',
              [orgId, `${user.name || "My"} workspace`, slug, now],
            );
            await pool.query(
              'INSERT INTO auth.member (id, "organizationId", "userId", role, "createdAt") VALUES ($1,$2,$3,$4,$5)',
              [crypto.randomUUID(), orgId, user.id, "admin", now],
            );
          },
        },
      },
      session: {
        create: {
          before: async (session) => {
            const s = session as typeof session & { activeOrganizationId?: string | null };
            if (s.activeOrganizationId) return { data: session };
            const r = await pool.query<{ organizationId: string }>(
              'SELECT "organizationId" FROM auth.member WHERE "userId" = $1 ORDER BY "createdAt" LIMIT 1',
              [session.userId],
            );
            return { data: { ...session, activeOrganizationId: r.rows[0]?.organizationId ?? null } };
          },
        },
      },
    },
    plugins: [
      organization({
        ac,
        roles: { guest: none, clerk: none, approver: none, controller: none, auditor: none, admin: orgAdmin },
        creatorRole: "admin",
        allowUserToCreateOrganization: async (user) => !(user as { isAnonymous?: boolean }).isAnonymous,
      }),
      anonymous({ emailDomainName: "guest.aura.invalid" }),
      jwt({
        jwt: {
          issuer: baseURL,
          audience: "aura-api",
          expirationTime: "15m",
          definePayload: async ({ user, session }) => {
            const active = (session as { activeOrganizationId?: string | null }).activeOrganizationId;
            const m = await membership(user.id, active);
            return {
              email: user.email,
              name: user.name,
              org_id: m.orgId,
              roles: m.roles,
              guest: Boolean((user as { isAnonymous?: boolean }).isAnonymous),
            };
          },
        },
      }),
      ...(turnstileSecret
        ? [
            captcha({
              provider: "cloudflare-turnstile",
              secretKey: turnstileSecret,
              endpoints: ["/sign-up/email", "/sign-in/email", "/sign-in/anonymous"],
            }),
          ]
        : []),
    ],
  };
}

export { Kysely };
