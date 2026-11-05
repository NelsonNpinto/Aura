import { redirect } from "next/navigation";
import { AppNav } from "@/components/app-nav";
import { getViewer } from "@/lib/viewer";

export const dynamic = "force-dynamic";

export default async function AppLayout({ children }: { children: React.ReactNode }) {
  const viewer = await getViewer();
  if (!viewer) redirect("/login?next=/app");
  return (
    <div className="flex min-h-screen flex-col md:flex-row">
      <AppNav name={viewer.name} orgName={viewer.orgName} roles={viewer.roles} isGuest={viewer.isGuest} />
      <main className="flex-1 px-4 py-6 sm:px-8">{children}</main>
    </div>
  );
}
