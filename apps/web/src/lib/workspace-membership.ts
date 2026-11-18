import type { Pool } from "pg";
import { isPurchasingDemoUser, PURCHASING_DEMO_ORG } from "./purchasing-demo";
import { parseRoles } from "./roles";

export async function resolveWorkspace(
  pool: Pool,
  userId: string,
  activeOrgId?: string | null,
) {
  const { rows } = await pool.query<{
    id: string;
    name: string;
    role: string;
    assigned_role: string | null;
  }>(
    `SELECT o.id, o.name, m.role, p.role AS assigned_role
     FROM auth.member m
     JOIN auth.organization o ON o.id = m."organizationId"
     LEFT JOIN ap.procurement_members p ON p.org_id = o.id AND p.user_id = m."userId"
     WHERE m."userId" = $1
     ORDER BY m."createdAt", o.id`,
    [userId],
  );
  const workspaces = rows.flatMap((row) => {
    const roles = parseRoles(row.role);
    if (row.assigned_role) {
      const role = roles.find((item) => item === row.assigned_role);
      return role
        ? [{ id: row.id, name: row.name, roles: [role], assigned: true }]
        : [];
    }
    return roles.length
      ? [{ id: row.id, name: row.name, roles, assigned: false }]
      : [];
  });
  const assigned = workspaces.filter((workspace) => workspace.assigned);
  const active = workspaces.find((workspace) => workspace.id === activeOrgId);
  const demo = isPurchasingDemoUser(userId)
    ? workspaces.find((workspace) => workspace.id === PURCHASING_DEMO_ORG)
    : undefined;
  return {
    selected:
      demo ?? active ?? (assigned.length === 1 ? assigned[0] : workspaces[0]),
    workspaces: workspaces.map(({ id, name }) => ({ id, name })),
  };
}
