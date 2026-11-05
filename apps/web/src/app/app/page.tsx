import { Card, Metric } from "@/components/ui";
import { UsagePanel } from "@/components/usage-panel";
import { getViewer } from "@/lib/viewer";

export const metadata = { title: "Dashboard" };

export default async function Dashboard() {
  const viewer = await getViewer();
  return (
    <div className="w-full space-y-6">
      <h1 className="text-2xl font-semibold">Dashboard</h1>
      <p className="text-sm text-muted">
        Signed in to <strong>{viewer?.orgName ?? "—"}</strong>.
      </p>
      <div className="grid gap-4 md:grid-cols-2">
        <UsagePanel />
        <Card className="grid grid-cols-2 gap-4">
          <Metric label="Straight-through rate" value={null} source="ai.dataset_runs (none yet)" />
          <Metric label="Route accuracy" value={null} source="ai.dataset_runs (none yet)" />
          <Metric label="Cost per invoice" value={null} source="ai.llm_calls (no invoice runs yet)" />
          <Metric label="p95 latency" value={null} source="ap.runs (none yet)" />
        </Card>
      </div>
    </div>
  );
}
