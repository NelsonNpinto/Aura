"use client";

import clsx from "clsx";
import { AlertTriangle, BookOpen, CheckSquare, FlaskConical, Inbox, LayoutDashboard, LogOut, Moon, Sun } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useTheme } from "next-themes";
import { useSyncExternalStore } from "react";
import { PersonaSwitcher } from "@/components/persona-switcher";
import { Badge } from "@/components/ui";
import { clearApiToken } from "@/lib/api";
import { authClient } from "@/lib/auth-client";
import type { Role } from "@/lib/roles";

type Props = { name: string; orgName: string | null; roles: Role[]; isGuest: boolean };

export function AppNav({ name, orgName, roles, isGuest }: Props) {
  const path = usePathname();
  const router = useRouter();
  const { resolvedTheme, setTheme } = useTheme();
  // false during SSR/hydration, true on the client: avoids a theme-icon hydration mismatch
  const mounted = useSyncExternalStore(() => () => {}, () => true, () => false);
  const demo = isGuest || orgName?.toLowerCase().includes("demo");
  const items = [
    { href: "/app", label: "Dashboard", icon: LayoutDashboard, show: true },
    { href: "/app/inbox", label: "Invoices", icon: Inbox, show: true },
    { href: "/app/approvals", label: "Approvals", icon: CheckSquare, show: true },
    { href: "/app/exceptions", label: "Exceptions", icon: AlertTriangle, show: true },
    { href: "/app/knowledge", label: "Knowledge", icon: BookOpen, show: true },
    { href: "/app/admin/playground", label: "Playground", icon: FlaskConical, show: roles.includes("admin") },
  ];
  return (
    <aside className="flex w-full flex-col border-b border-border bg-surface md:min-h-screen md:w-60 md:border-b-0 md:border-r">
      <div className="flex items-center justify-between px-4 py-4">
        <Link href="/app" className="text-lg font-semibold">AURA</Link>
        {isGuest && <Badge tone="warn">guest</Badge>}
      </div>
      <nav className="flex gap-1 overflow-x-auto px-2 md:flex-col" aria-label="Main">
        {items.filter((i) => i.show).map(({ href, label, icon: Icon }) => (
          <Link key={href} href={href}
            className={clsx("flex items-center gap-2 rounded-md px-3 py-2 text-sm",
              path === href || (href !== "/app" && path.startsWith(href)) ? "bg-surface-2 font-medium" : "text-muted hover:bg-surface-2")}>
            <Icon size={16} aria-hidden /> {label}
          </Link>
        ))}
      </nav>
      {demo && <PersonaSwitcher />}
      <div className="mt-auto hidden space-y-2 border-t border-border p-4 text-sm md:block">
        <div className="font-medium">{name || "Guest"}</div>
        <div className="text-xs text-muted">{orgName ?? "No organization"}</div>
        <div className="flex flex-wrap gap-1">{roles.map((r) => <Badge key={r}>{r}</Badge>)}</div>
        <div className="flex gap-2 pt-2">
          <button className="rounded p-1.5 hover:bg-surface-2" aria-label="Toggle dark mode"
            onClick={() => setTheme(resolvedTheme === "dark" ? "light" : "dark")}>
            {mounted && resolvedTheme === "dark" ? <Sun size={16} /> : <Moon size={16} />}
          </button>
          <button className="flex items-center gap-1 rounded p-1.5 hover:bg-surface-2" onClick={async () => {
            clearApiToken();
            await authClient.signOut();
            router.push("/");
            router.refresh();
          }}>
            <LogOut size={16} aria-hidden /> Sign out
          </button>
        </div>
      </div>
    </aside>
  );
}
