import "server-only";
import { headers } from "next/headers";
import { cache } from "react";
import { auth } from "./auth";
import { pool } from "./db";
import type { Role } from "./roles";
import { resolveWorkspace } from "./workspace-membership";

export type Viewer = {
  userId: string;
  name: string;
  email: string;
  isGuest: boolean;
  orgId: string | null;
  orgName: string | null;
  roles: Role[];
  workspaces: { id: string; name: string }[];
};

export const getViewer = cache(async (): Promise<Viewer | null> => {
  const session = await auth.api.getSession({ headers: await headers() });
  if (!session) return null;
  const active = (session.session as { activeOrganizationId?: string | null }).activeOrganizationId ?? null;
  const { selected, workspaces } = await resolveWorkspace(pool, session.user.id, active);
  return {
    userId: session.user.id,
    name: session.user.name,
    email: session.user.email,
    isGuest: Boolean((session.user as { isAnonymous?: boolean }).isAnonymous),
    orgId: selected?.id ?? null,
    orgName: selected?.name ?? null,
    roles: selected?.roles ?? [],
    workspaces,
  };
});
