/** AURA roles (§B1). Kept in one place for the web app; the API has its own allow-list. */
export const ROLES = ["guest", "clerk", "approver", "controller", "auditor", "admin", "vendor", "purchasing", "receiving", "finance"] as const;
export type Role = (typeof ROLES)[number];

export const DEMO_ORG_ID = "demo";

export function parseRoles(raw: string | null | undefined): Role[] {
  if (!raw) return [];
  return raw
    .split(",")
    .map((r) => r.trim())
    .filter((r): r is Role => (ROLES as readonly string[]).includes(r));
}
