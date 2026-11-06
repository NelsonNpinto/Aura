import { redirect } from "next/navigation";
import { AppNav } from "@/components/app-nav";
import { getViewer } from "@/lib/viewer";

export const dynamic = "force-dynamic";

export default async function AppLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const viewer = await getViewer();
  if (!viewer) redirect("/login?next=/app");
  return (
    <div className="min-h-screen lg:grid lg:grid-cols-[15rem_minmax(0,1fr)]">
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:fixed focus:z-50 focus:m-3 focus:rounded-lg focus:bg-surface focus:p-3"
      >
        Skip to content
      </a>
      <AppNav
        name={viewer.name}
        orgName={viewer.orgName}
        roles={viewer.roles}
        isGuest={viewer.isGuest}
      />
      <main
        id="main-content"
        tabIndex={-1}
        className="workspace-content mx-auto w-full min-w-0 max-w-7xl px-4 py-7 sm:px-7 lg:px-9 lg:py-10"
      >
        {children}
      </main>
    </div>
  );
}
