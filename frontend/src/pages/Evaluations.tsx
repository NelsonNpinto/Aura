import { useState } from "react";
import { useLocation } from "react-router-dom";
import { Check, FlaskConical, Loader2, X } from "lucide-react";
import { toast } from "sonner";
import {
  Badge,
  Empty,
  ErrorState,
  Loading,
  PageHeading,
  PanelTitle,
} from "../components/common";
import { Button } from "../components/ui/button";
import { useApi } from "../hooks/useApi";
import { api, errorMessage } from "../services/api";
import { date, number } from "../lib/utils";
import type { CheckKind, Evaluation } from "../types";
const options: { kind: CheckKind; label: string; description: string }[] = [
  {
    kind: "non_empty",
    label: "Non-empty response",
    description: "The response must contain text.",
  },
  {
    kind: "valid_json",
    label: "Valid JSON",
    description: "The entire response must parse as JSON.",
  },
  {
    kind: "required_keywords",
    label: "Required keywords",
    description: "Every keyword must appear, ignoring case.",
  },
  {
    kind: "forbidden_phrases",
    label: "Forbidden phrases",
    description: "None of these phrases may appear, ignoring case.",
  },
  {
    kind: "exact_match",
    label: "Exact answer",
    description: "Match expected text after trimming whitespace.",
  },
  {
    kind: "json_schema",
    label: "JSON schema",
    description: "Validate structure and required fields.",
  },
];
export function Evaluations() {
  const location = useLocation(),
    initial = location.state as { response?: string; trace_id?: string } | null;
  const history = useApi<Evaluation[]>("/evaluations");
  const [name, setName] = useState("Response evaluation"),
    [response, setResponse] = useState(initial?.response ?? ""),
    [selected, setSelected] = useState<CheckKind[]>(["non_empty"]),
    [keywords, setKeywords] = useState(""),
    [forbidden, setForbidden] = useState(""),
    [expected, setExpected] = useState(""),
    [schema, setSchema] = useState(
      '{"type":"object","required":["answer"],"properties":{"answer":{"type":"string"}}}',
    ),
    [threshold, setThreshold] = useState(100),
    [busy, setBusy] = useState(false),
    [result, setResult] = useState<Evaluation | null>(null),
    [error, setError] = useState<string | null>(null);
  const toggle = (kind: CheckKind) =>
    setSelected((s) =>
      s.includes(kind) ? s.filter((v) => v !== kind) : [...s, kind],
    );
  async function run() {
    setBusy(true);
    setError(null);
    try {
      const checks = selected.map((kind) => ({
        kind,
        ...(kind === "required_keywords"
          ? {
              values: keywords
                .split(",")
                .map((s) => s.trim())
                .filter(Boolean),
            }
          : {}),
        ...(kind === "forbidden_phrases"
          ? {
              values: forbidden
                .split(",")
                .map((s) => s.trim())
                .filter(Boolean),
            }
          : {}),
        ...(kind === "exact_match" ? { expected } : {}),
        ...(kind === "json_schema"
          ? { schema_definition: JSON.parse(schema) }
          : {}),
      }));
      const { data } = await api.post<Evaluation>("/evaluations", {
        name,
        response,
        checks,
        threshold: threshold / 100,
        trace_id: initial?.response === response ? initial.trace_id : undefined,
      });
      setResult(data);
      void history.refresh();
      toast.success("Evaluation saved");
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <PageHeading
        eyebrow="TEST & MEASURE"
        title="Evaluations"
        description="Turn output expectations into explicit, reproducible checks."
      />
      <div className="info-banner">
        <FlaskConical size={20} />
        <div>
          <strong>Deterministic checks</strong>
          <p>
            These rules measure output compliance. They do not measure factual
            correctness, faithfulness, or hallucination.
          </p>
        </div>
        <Badge>No model required</Badge>
      </div>
      <div className="evaluation-grid">
        <section className="panel">
          <PanelTitle
            title="New evaluation"
            description="Paste a response or send one here from the playground."
          />
          <form
            className="form-body"
            onSubmit={(e) => {
              e.preventDefault();
              void run();
            }}
          >
            <label>
              Evaluation name
              <input
                required
                value={name}
                maxLength={200}
                onChange={(e) => setName(e.target.value)}
              />
            </label>
            <label>
              Response to evaluate
              <textarea
                rows={8}
                value={response}
                maxLength={64000}
                onChange={(e) => setResponse(e.target.value)}
                placeholder="Paste the AI-generated response here. Leave empty to test empty-response detection."
              />
            </label>
            <div>
              <span className="field-label">Output checks</span>
              <div className="check-options">
                {options.map((o) => (
                  <label
                    className={`check-option ${selected.includes(o.kind) ? "selected" : ""}`}
                    key={o.kind}
                  >
                    <input
                      type="checkbox"
                      checked={selected.includes(o.kind)}
                      onChange={() => toggle(o.kind)}
                    />
                    <span>
                      <strong>{o.label}</strong>
                      <small>{o.description}</small>
                    </span>
                  </label>
                ))}
              </div>
            </div>
            {selected.includes("required_keywords") && (
              <label>
                Required keywords, separated by commas
                <input
                  required
                  value={keywords}
                  onChange={(e) => setKeywords(e.target.value)}
                  placeholder="refund, 30 days"
                />
              </label>
            )}
            {selected.includes("forbidden_phrases") && (
              <label>
                Forbidden phrases, separated by commas
                <input
                  required
                  value={forbidden}
                  onChange={(e) => setForbidden(e.target.value)}
                  placeholder="guaranteed, 100% accurate"
                />
              </label>
            )}
            {selected.includes("exact_match") && (
              <label>
                Expected answer
                <textarea
                  rows={3}
                  value={expected}
                  onChange={(e) => setExpected(e.target.value)}
                />
              </label>
            )}
            {selected.includes("json_schema") && (
              <label>
                JSON Schema (inline, no references)
                <textarea
                  className="code-input"
                  rows={5}
                  required
                  value={schema}
                  onChange={(e) => setSchema(e.target.value)}
                />
              </label>
            )}
            <label>
              Pass threshold (%)
              <input
                type="number"
                min="0"
                max="100"
                value={threshold}
                required
                onChange={(e) => setThreshold(+e.target.value)}
              />
              <small>
                Equal-weight score: passed checks divided by total checks.
              </small>
            </label>
            {error && (
              <div className="inline-error" role="alert">
                {error}
              </div>
            )}
            <Button disabled={busy || !selected.length} type="submit">
              {busy ? (
                <Loader2 size={16} className="animate-spin" />
              ) : (
                <FlaskConical size={16} />
              )}
              Run evaluation
            </Button>
          </form>
        </section>
        <div className="evaluation-side">
          <section className="panel">
            <PanelTitle
              title="Evaluation result"
              description="Every score comes with an explanation."
            />
            {result ? (
              <div className="result-body">
                <div className="result-score">
                  <strong>
                    {number(result.score * 100)}
                    <span>%</span>
                  </strong>
                  <Badge good={result.passed}>
                    {result.passed ? "Passed" : "Failed"}
                  </Badge>
                </div>
                <p className="muted-text">
                  {result.name} ·{" "}
                  {result.results.filter((r) => r.passed).length} of{" "}
                  {result.results.length} checks passed
                </p>
                <div className="result-checks">
                  {result.results.map((r, i) => (
                    <div key={i}>
                      {r.passed ? (
                        <Check size={17} className="text-green-700" />
                      ) : (
                        <X size={17} className="text-red-600" />
                      )}
                      <div>
                        <strong>
                          {options.find((o) => o.kind === r.kind)?.label}
                        </strong>
                        <p>{r.detail}</p>
                      </div>
                    </div>
                  ))}
                </div>
                <small className="muted-text">
                  Saved · {date(result.created_at)}
                </small>
              </div>
            ) : (
              <Empty title="Evidence over assumptions">
                Run your checks to see a score
                <br />
                and an explanation for every result.
              </Empty>
            )}
          </section>
          <div className="learning-note">
            <h3>What makes a good check?</h3>
            <p>
              Start with rules you can verify: required fields, approved terms,
              or a precise output format. Add model-based judgments later for
              questions that need interpretation.
            </p>
          </div>
        </div>
      </div>
      <section className="panel history-panel">
        <PanelTitle
          title="Evaluation history"
          description="Stored runs with their original rules and response."
        />
        {history.error ? (
          <ErrorState message={history.error} retry={history.refresh} />
        ) : history.loading ? (
          <Loading />
        ) : history.data?.length ? (
          <div className="history-list">
            {history.data.map((r) => (
              <details key={r.id}>
                <summary>
                  <span>
                    {r.name}
                    <small>{date(r.created_at)}</small>
                  </span>
                  <Badge good={r.passed}>
                    {r.passed ? "Passed" : "Failed"}
                  </Badge>
                  <strong>{number(r.score * 100)}%</strong>
                </summary>
                <div className="history-detail">
                  <pre>{r.response || "(empty response)"}</pre>
                  {r.results.map((c, i) => (
                    <p key={i}>
                      <Badge good={c.passed}>
                        {c.kind.replaceAll("_", " ")}
                      </Badge>{" "}
                      {c.detail}
                    </p>
                  ))}
                </div>
              </details>
            ))}
          </div>
        ) : (
          <Empty title="Your evaluation history starts here">
            Completed runs are saved automatically.
          </Empty>
        )}
      </section>
    </>
  );
}
