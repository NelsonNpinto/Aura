import type { ReactNode } from "react";
import { Loader2, RefreshCw } from "lucide-react";
import { useModels } from "../contexts/ModelsContext";
import { Badge, Empty, ErrorState, Loading, PanelTitle } from "./common";
import { Button } from "./ui/button";
import type { Rule } from "../types/platform";
import { date } from "../lib/utils";
export function ModelPicker({
  value,
  onChange,
  required = true,
}: {
  required?: boolean;
  value: string;
  onChange: (v: string) => void;
}) {
  const models = useModels();
  return (
    <label>
      Local model
      <div className="model-picker">
        <select
          required={required}
          value={value}
          onChange={(e) => onChange(e.target.value)}
        >
          <option value="">Select an installed model</option>
          {models.data?.models.map((m) => (
            <option key={m.name}>{m.name}</option>
          ))}
        </select>
        <Button
          type="button"
          variant="outline"
          size="icon"
          onClick={() => void models.refresh()}
          aria-label="Refresh models"
        >
          <RefreshCw size={14} />
        </Button>
      </div>
      {!models.data?.models.length && (
        <small>No models installed. See Settings for the pull command.</small>
      )}
    </label>
  );
}
export function ActionButton({
  busy,
  children,
  disabled = false,
}: {
  busy: boolean;
  children: ReactNode;
  disabled?: boolean;
}) {
  return (
    <Button type="submit" disabled={busy || disabled}>
      {busy && <Loader2 size={15} className="animate-spin" />}
      {busy ? "Working…" : children}
    </Button>
  );
}
export function MutationError({ error }: { error: string | null }) {
  return error ? (
    <div className="inline-error" role="alert">
      {error}
    </div>
  ) : null;
}
export function Note({
  title,
  children,
}: {
  title: string;
  children: ReactNode;
}) {
  return (
    <div className="learning-note">
      <h3>{title}</h3>
      <p>{children}</p>
    </div>
  );
}
export function DataPanel<T extends { id: string; created_at: string }>({
  title,
  query,
  render,
  empty = "No records yet",
}: {
  title: string;
  query: {
    data: T[] | null;
    error: string | null;
    loading: boolean;
    refresh: () => void;
  };
  render: (r: T) => ReactNode;
  empty?: string;
}) {
  return (
    <section className="panel history-panel">
      <PanelTitle
        title={title}
        action={
          <Button
            size="sm"
            variant="ghost"
            onClick={() => void query.refresh()}
          >
            <RefreshCw size={13} />
            Refresh
          </Button>
        }
      />
      {query.error ? (
        <ErrorState message={query.error} retry={query.refresh} />
      ) : query.loading ? (
        <Loading />
      ) : query.data?.length ? (
        <div className="record-list">
          {query.data.map((r) => (
            <article key={r.id} className="record-item">
              {render(r)}
              <small className="record-time">
                {date(r.created_at)} · {r.id.slice(0, 8)}
              </small>
            </article>
          ))}
        </div>
      ) : (
        <Empty title={empty}>Your saved records will appear here.</Empty>
      )}
    </section>
  );
}
export function Inspect({
  value,
  label = "Inspect configuration & results",
}: {
  value: unknown;
  label?: string;
}) {
  return (
    <details className="inspect">
      <summary>{label}</summary>
      <pre>{JSON.stringify(value, null, 2)}</pre>
    </details>
  );
}
export function Checks({
  results,
}: {
  results: { kind: string; passed: boolean; detail: string }[];
}) {
  return (
    <div className="checks-list">
      {results.map((r, i) => (
        <div key={i}>
          <Badge good={r.passed}>{r.passed ? "Pass" : "Fail"}</Badge>
          <strong>{r.kind.replaceAll("_", " ")}</strong>
          <p>{r.detail}</p>
        </div>
      ))}
    </div>
  );
}
export function RulesEditor({
  value,
  onChange,
}: {
  value: Rule[];
  onChange: (v: Rule[]) => void;
}) {
  const has = (kind: Rule["kind"]) => value.some((v) => v.kind === kind);
  const toggle = (kind: Rule["kind"]) =>
    onChange(
      has(kind)
        ? value.filter((v) => v.kind !== kind)
        : [
            ...value,
            {
              kind,
              ...(kind === "exact_match" ? { expected: "" } : {}),
              ...(kind === "json_schema"
                ? {
                    schema_definition: { type: "object", required: ["answer"] },
                  }
                : {}),
            },
          ],
    );
  const update = (kind: Rule["kind"], patch: Partial<Rule>) =>
    onChange(value.map((v) => (v.kind === kind ? { ...v, ...patch } : v)));
  return (
    <fieldset className="rules-editor">
      <legend>Pass conditions</legend>
      <div className="rule-toggles">
        {(
          [
            "non_empty",
            "valid_json",
            "required_keywords",
            "forbidden_phrases",
            "exact_match",
          ] as const
        ).map((kind) => (
          <label key={kind}>
            <input
              type="checkbox"
              checked={has(kind)}
              onChange={() => toggle(kind)}
            />
            {kind.replaceAll("_", " ")}
          </label>
        ))}
      </div>
      {value.map((v) =>
        v.kind === "required_keywords" || v.kind === "forbidden_phrases" ? (
          <label key={v.kind}>
            {v.kind.replaceAll("_", " ")} (comma-separated)
            <input
              required
              value={v.values?.join(", ") ?? ""}
              onChange={(e) =>
                update(v.kind, {
                  values: e.target.value.split(",").map((s) => s.trim()),
                })
              }
            />
          </label>
        ) : v.kind === "exact_match" ? (
          <label key={v.kind}>
            Expected exact answer
            <textarea
              rows={2}
              value={v.expected ?? ""}
              onChange={(e) => update(v.kind, { expected: e.target.value })}
            />
          </label>
        ) : null,
      )}
      {!value.length && <small>Select at least one check.</small>}
    </fieldset>
  );
}
export const splitList = (s: string) =>
  s
    .split("\n")
    .map((v) => v.trim())
    .filter(Boolean);
