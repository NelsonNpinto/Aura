import type { BetterAuthOptions } from "better-auth";
import { APIError, createAuthMiddleware, getSessionFromCtx } from "better-auth/api";
import { anonymous, jwt, organization } from "better-auth/plugins";
import { createAccessControl } from "better-auth/plugins/access";
import { defaultStatements } from "better-auth/plugins/organization/access";
import { Kysely, PostgresDialect } from "kysely";
import type { Pool } from "pg";
import { DEMO_ORG_ID } from "./roles";
import { isPurchasingDemoUser, PURCHASING_DEMO_DOMAIN } from "./purchasing-demo";
import { resolveWorkspace } from "./workspace-membership";

const ac = createAccessControl({ ...defaultStatements });
const none = ac.newRole({ organization: [], member: [], invitation: [] });
const orgAdmin = ac.newRole({
  organization: ["update"],
  member: ["create", "update", "delete"],
  invitation: ["create", "cancel"],
});

export function buildAuthOptions(pool: Pool): BetterAuthOptions {
  const baseURL = process.env.BETTER_AUTH_URL ?? "http://localhost:3000";

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
    hooks: {
      before: createAuthMiddleware(async (ctx) => {
        if (!["/change-password", "/change-email", "/update-user", "/delete-user", "/link-social", "/unlink-account", "/organization/leave"].includes(ctx.path)) return;
        const session = await getSessionFromCtx(ctx);
        if (session && isPurchasingDemoUser(session.user.id)) {
          throw new APIError("FORBIDDEN", { message: "Shared demo accounts cannot be changed" });
        }
      }),
    },
    databaseHooks: {
      user: {
        create: {
          before: async (user) => {
            if (user.email.toLowerCase().endsWith(`@${PURCHASING_DEMO_DOMAIN}`)) {
              throw new APIError("FORBIDDEN", { message: "This email domain is reserved for the Purchasing demo" });
            }
          },
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
            const { selected } = await resolveWorkspace(pool, session.userId, s.activeOrganizationId);
            return { data: { ...session, activeOrganizationId: selected?.id ?? null } };
          },
        },
      },
    },
    plugins: [
      organization({
        ac,
        roles: { vendor: none, purchasing: none, receiving: none, finance: none, guest: none, clerk: none, approver: none, controller: none, auditor: none, admin: orgAdmin },
        creatorRole: "admin",
        allowUserToCreateOrganization: async (user) =>
          !(user as { isAnonymous?: boolean }).isAnonymous && !isPurchasingDemoUser(user.id),
      }),
      anonymous({ emailDomainName: "guest.aura.invalid" }),
      jwt({
        disableSettingJwtHeader: true,
        jwt: {
          issuer: baseURL,
          audience: "aura-api",
          expirationTime: "15m",
          definePayload: async ({ user, session }) => {
            const active = (session as { activeOrganizationId?: string | null }).activeOrganizationId;
            const { selected } = await resolveWorkspace(pool, user.id, active);
            return {
              email: user.email,
              name: user.name,
              org_id: selected?.id ?? null,
              roles: selected?.roles ?? [],
              guest: Boolean((user as { isAnonymous?: boolean }).isAnonymous),
            };
          },
        },
      }),
    ],
  };
}

export { Kysely };
