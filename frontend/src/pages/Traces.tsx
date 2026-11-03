import { useState } from "react";
import { Search } from "lucide-react";
import {
  Badge,
  Empty,
  ErrorState,
  Loading,
  PageHeading,
  PanelTitle,
} from "../components/common";
import { useApi } from "../hooks/useApi";
import { date, number } from "../lib/utils";
import type { Trace } from "../types";
export function Traces() {
  const { data, error, loading, refresh } = useApi<Trace[]>("/traces");
  const [query, setQuery] = useState(""),
    [selected, setSelected] = useState<Trace | null>(null);
  const filtered = data?.filter((t) =>
    [t.id, t.model, t.prompt, t.status].some((v) =>
      v.toLowerCase().includes(query.toLowerCase()),
    ),
  );
  return (
    <>
      <PageHeading
        eyebrow="OBSERVE & DEBUG"
        title="Request traces"
        description="Follow each model request from its prompt to its final output."
      />
      <section className="panel">
        <PanelTitle
          title="Recorded requests"
          description="The most recent 100 requests, including failed attempts."
          action={
            <label className="search-field">
              <Search size={16} />
              <input
                aria-label="Search traces"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search model, prompt, or ID…"
              />
            </label>
          }
        />
        {error ? (
          <ErrorState message={error} retry={refresh} />
        ) : loading ? (
          <Loading />
        ) : filtered?.length ? (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Request</th>
                  <th>Model</th>
                  <th>Status</th>
                  <th>Latency</th>
                  <th>Tokens in / out</th>
                  <th>Created</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((t) => (
                  <tr key={t.id}>
                    <td>
                      <button
                        className="text-link"
                        onClick={() => setSelected(t)}
                      >
                        {t.id.slice(0, 8)}
                      </button>
                      <small className="truncate-prompt">{t.prompt}</small>
                    </td>
                    <td>{t.model}</td>
                    <td>
                      <Badge good={t.status === "success"}>{t.status}</Badge>
                    </td>
                    <td>{number(t.latency_ms / 1000, 2)}s</td>
                    <td>
                      {number(t.input_tokens)} / {number(t.output_tokens)}
                    </td>
                    <td>{date(t.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <Empty
            title={query ? "No matching traces" : "Every request has a story"}
          >
            {query
              ? "Try another search."
              : "Run a prompt in the playground to capture your first trace."}
          </Empty>
        )}
      </section>
      {selected && (
        <section className="panel trace-detail">
          <PanelTitle
            title={`Request ${selected.id.slice(0, 8)}`}
            description={selected.id}
            action={
              <button className="text-link" onClick={() => setSelected(null)}>
                Close
              </button>
            }
          />
          <div className="form-body">
            <Badge good={selected.status === "success"}>
              {selected.status}
            </Badge>
            <label>
              System instructions<pre>{selected.system || "(none)"}</pre>
            </label>
            <label>
              Prompt<pre>{selected.prompt}</pre>
            </label>
            <label>
              Configuration
              <pre>{JSON.stringify(selected.configuration, null, 2)}</pre>
            </label>
            <label>
              Response<pre>{selected.response ?? "(no response)"}</pre>
            </label>
            {selected.error && (
              <div className="inline-error">{selected.error}</div>
            )}
          </div>
        </section>
      )}
    </>
  );
}
