"use client";

import clsx from "clsx";
import {
  AlertTriangle,
  BookOpen,
  CheckSquare,
  FlaskConical,
  Inbox,
  Layers3,
  LayoutDashboard,
  LogOut,
  Menu,
  MessageSquare,
  Moon,
  ShoppingBag,
  Sun,
  X,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useTheme } from "next-themes";
import { useState, useSyncExternalStore } from "react";
import { PersonaSwitcher } from "@/components/persona-switcher";
import { Badge } from "@/components/ui";
import { clearApiToken } from "@/lib/api";
import { authClient } from "@/lib/auth-client";
import type { Role } from "@/lib/roles";

type Props = {
  name: string;
  orgName: string | null;
  roles: Role[];
  isGuest: boolean;
};

export function AppNav({ name, orgName, roles, isGuest }: Props) {
  const path = usePathname();
  const router = useRouter();
  const { resolvedTheme, setTheme } = useTheme();
  // false during SSR/hydration, true on the client: avoids a theme-icon hydration mismatch
  const mounted = useSyncExternalStore(
    () => () => {},
    () => true,
    () => false,
  );
  const demo = isGuest || orgName?.toLowerCase().includes("demo");
  const [openPath, setOpenPath] = useState<string | null>(null);
  const menuOpen = openPath === path;
  const vendor = roles.includes("vendor");
  const groups = [
    {
      label: "Workspace",
      items: [
        {
          href: "/app",
          label: "Dashboard",
          icon: LayoutDashboard,
          show: !vendor,
        },
        {
          href: "/app/procurement",
          label: "Purchasing",
          icon: ShoppingBag,
          show: true,
        },
      ],
    },
    {
      label: "Invoice workflow",
      items: [
        { href: "/app/inbox", label: "Invoices", icon: Inbox, show: !vendor },
        {
          href: "/app/approvals",
          label: "Approvals",
          icon: CheckSquare,
          show: !vendor,
        },
        {
          href: "/app/exceptions",
          label: "Exceptions",
          icon: AlertTriangle,
          show: !vendor,
        },
      ],
    },
    {
      label: "AI tools",
      items: [
        {
          href: "/app/copilot",
          label: "Copilot",
          icon: MessageSquare,
          show: !vendor,
        },
        {
          href: "/app/knowledge",
          label: "Knowledge",
          icon: BookOpen,
          show: !vendor,
        },
        {
          href: "/app/quality",
          label: "AI quality",
          icon: FlaskConical,
          show: !vendor,
        },
        {
          href: "/app/admin/playground",
          label: "Playground",
          icon: FlaskConical,
          show: !vendor && roles.includes("admin"),
        },
      ],
    },
  ];
  return (
    <aside className="workspace-nav flex w-full flex-col bg-surface lg:sticky lg:top-0 lg:h-dvh lg:overflow-y-auto">
      <div className="flex items-center justify-between gap-2 p-4 lg:mb-2 lg:px-5 lg:py-6">
        <Link
          href={vendor ? "/app/procurement" : "/app"}
          className="flex items-center gap-3 rounded-md"
          onClick={() => setOpenPath(null)}
        >
          <span className="grid size-9 place-items-center rounded-lg bg-accent text-accent-fg">
            <Layers3 size={19} aria-hidden />
          </span>
          <span>
            <span className="block font-bold tracking-wide">AURA</span>
            <span className="block text-xs text-muted">Finance workspace</span>
          </span>
        </Link>
        <div className="flex items-center gap-2">
          {isGuest && <Badge>Guest</Badge>}
          <button
            id="workspace-menu-toggle"
            type="button"
            className="grid size-10 place-items-center rounded-lg hover:bg-surface-2 lg:hidden"
            aria-label={menuOpen ? "Close navigation" : "Open navigation"}
            aria-expanded={menuOpen}
            aria-controls="workspace-navigation"
            onClick={() => setOpenPath(menuOpen ? null : path)}
          >
            {menuOpen ? <X size={20} /> : <Menu size={20} />}
          </button>
        </div>
      </div>
      <div
        id="workspace-navigation"
        className={clsx(
          "flex-1 flex-col lg:flex",
          menuOpen ? "flex" : "hidden",
        )}
        onKeyDown={(event) => {
          if (event.key === "Escape" && menuOpen) {
            setOpenPath(null);
            document.getElementById("workspace-menu-toggle")?.focus();
          }
        }}
      >
        <nav className="space-y-4 px-3 pb-4" aria-label="Main">
          {groups
            .filter(({ items }) => items.some(({ show }) => show))
            .map(({ label: group, items }) => (
              <div key={group} className="space-y-1">
                <p className="px-3 text-[11px] font-semibold tracking-wider text-muted uppercase">
                  {group}
                </p>
                {items
                  .filter(({ show }) => show)
                  .map(({ href, label, icon: Icon }) => {
                    const active =
                      path === href ||
                      (href !== "/app" && path.startsWith(href + "/")) ||
                      (href === "/app/inbox" &&
                        /^\/app\/(runs|invoices)\//.test(path));
                    return (
                      <Link
                        key={href}
                        href={href}
                        aria-current={active ? "page" : undefined}
                        onClick={() => setOpenPath(null)}
                        className={clsx(
                          "flex min-h-10 items-center gap-3 rounded-lg px-3 text-sm transition",
                          active
                            ? "bg-accent/15 font-semibold text-accent"
                            : "text-muted hover:bg-surface-2 hover:text-text",
                        )}
                      >
                        <Icon size={17} aria-hidden /> {label}
                      </Link>
                    );
                  })}
              </div>
            ))}
        </nav>
        {demo && <PersonaSwitcher />}
        <div className="mt-auto space-y-2 border-t border-border p-4 text-sm">
          <div className="truncate font-medium">{name || "Guest"}</div>
          <div
            className="truncate text-xs text-muted"
            title={orgName ?? undefined}
          >
            {orgName ?? "No organization"}
          </div>
          <div className="flex flex-wrap gap-1">
            {roles.map((r) => (
              <Badge key={r}>{r}</Badge>
            ))}
          </div>
          <div className="flex gap-2 pt-2">
            <button
              className="grid size-9 place-items-center rounded-lg hover:bg-surface-2"
              aria-label="Toggle dark mode"
              onClick={() =>
                setTheme(resolvedTheme === "dark" ? "light" : "dark")
              }
            >
              {mounted && resolvedTheme === "dark" ? (
                <Sun size={16} />
              ) : (
                <Moon size={16} />
              )}
            </button>
            <button
              className="flex min-h-9 items-center gap-2 rounded-lg px-2 text-muted hover:bg-surface-2 hover:text-text"
              onClick={async () => {
                clearApiToken();
                await authClient.signOut();
                router.push("/");
                router.refresh();
              }}
            >
              <LogOut size={16} aria-hidden /> Sign out
            </button>
          </div>
        </div>
      </div>
    </aside>
  );
}
