import "server-only";
import { headers } from "next/headers";
import { auth } from "./auth";
import { pool } from "./db";
import { parseRoles, type Role } from "./roles";

export type Viewer = {
  userId: string;
  name: string;
  email: string;
  isGuest: boolean;
  orgId: string | null;
  orgName: string | null;
  roles: Role[];
};

export async function getViewer(): Promise<Viewer | null> {
  const session = await auth.api.getSession({ headers: await headers() });
  if (!session) return null;
  const active = (session.session as { activeOrganizationId?: string | null }).activeOrganizationId ?? null;
  const r = await pool.query<{ role: string; name: string; id: string }>(
    `SELECT m.role, o.name, o.id FROM auth.member m JOIN auth.organization o ON o.id = m."organizationId"
     WHERE m."userId" = $1 ORDER BY (o.id = $2) DESC NULLS LAST, m."createdAt" LIMIT 1`,
    [session.user.id, active],
  );
  const roles: Role[] = parseRoles(r.rows[0]?.role);
  const orgName = r.rows[0]?.name ?? null;
  const orgId = r.rows[0]?.id ?? null;
  return {
    userId: session.user.id,
    name: session.user.name,
    email: session.user.email,
    isGuest: Boolean((session.user as { isAnonymous?: boolean }).isAnonymous),
    orgId,
    orgName,
    roles,
  };
}
