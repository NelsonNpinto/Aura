import { useState } from "react";
import { Badge, PageHeading, PanelTitle } from "../components/common";
import {
  ActionButton,
  DataPanel,
  Inspect,
  MutationError,
  Note,
  RulesEditor,
} from "../components/platform";
import { useApi } from "../hooks/useApi";
import { useMutation } from "../hooks/useMutation";
import { api } from "../services/api";
import type { Dataset, FailureEvent, Rule } from "../types/platform";
export function FailureInbox() {
  const failures = useApi<FailureEvent[]>("/failures"),
    datasets = useApi<Dataset[]>("/datasets"),
    action = useMutation<unknown>();
  const [selected, setSelected] = useState<FailureEvent | null>(null),
    [dataset, setDataset] = useState(""),
    [expected, setExpected] = useState(""),
    [rules, setRules] = useState<Rule[]>([{ kind: "non_empty" }]);
  return (
    <>
      <PageHeading
        eyebrow="FROM FAILURE TO COVERAGE"
        title="Failure Inbox"
        description="Inspect incoming failures and approve them into regression datasets."
      />
      <Note title="Authenticated, deduplicated ingestion">
        External applications can POST failure events to
        /api/v1/webhooks/ai-failure using a Bearer WEBHOOK_SECRET. Repeated
        event IDs with the same content return the original failure. Conflicting
        reuse is rejected. Configure the secret in your server environment.
      </Note>
      <section className="panel section-gap">
        <PanelTitle title="Webhook event shape" />
        <div className="form-body">
          <pre>
            {JSON.stringify(
              {
                event_id: "your-unique-event-id",
                source: "support-assistant",
                question: "What is the refund policy?",
                response: "An unsupported answer",
                error: "Policy violation",
                metadata: { environment: "development" },
              },
              null,
              2,
            )}
          </pre>
        </div>
      </section>
      <DataPanel
        title="Received failures"
        query={failures}
        empty="No incoming failure events"
        render={(r) => (
          <>
            <div className="record-heading">
              <h3>
                {r.source} · {r.question}
              </h3>
              <Badge good={r.status === "approved"}>{r.status}</Badge>
              {r.status !== "approved" && (
                <button className="text-link" onClick={() => setSelected(r)}>
                  Review for regression coverage
                </button>
              )}
            </div>
            <p className="inline-error">{r.error}</p>
            <Inspect value={r} />
          </>
        )}
      />
      {selected && (
        <section className="panel section-gap">
          <PanelTitle
            title="Approve as a test case"
            description={selected.question}
          />
          <form
            className="form-body"
            onSubmit={(e) => {
              e.preventDefault();
              void action.execute(
                async () =>
                  (
                    await api.post(`/failures/${selected.id}/approve`, {
                      dataset_id: dataset,
                      expected: expected || null,
                      checks: rules,
                    })
                  ).data,
                "Failure added to regression dataset",
                () => {
                  void failures.refresh();
                  setSelected(null);
                },
              );
            }}
          >
            <pre>{selected.response || "(empty response)"}</pre>
            <label>
              Destination dataset
              <select
                required
                value={dataset}
                onChange={(e) => setDataset(e.target.value)}
              >
                <option value="">Choose a dataset</option>
                {datasets.data?.map((d) => (
                  <option value={d.id} key={d.id}>
                    {d.name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Expected correct answer
              <textarea
                rows={3}
                value={expected}
                onChange={(e) => setExpected(e.target.value)}
              />
            </label>
            <RulesEditor value={rules} onChange={setRules} />
            <MutationError error={action.error} />
            <ActionButton busy={action.busy} disabled={!rules.length}>
              Approve into regression tests
            </ActionButton>
          </form>
        </section>
      )}
    </>
  );
}
