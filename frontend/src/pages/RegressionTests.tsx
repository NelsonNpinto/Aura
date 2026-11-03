import { useState } from "react";
import { Badge, PageHeading, PanelTitle } from "../components/common";
import {
  ActionButton,
  DataPanel,
  Inspect,
  ModelPicker,
  MutationError,
  Note,
  RulesEditor,
  splitList,
} from "../components/platform";
import { Button } from "../components/ui/button";
import { useApi } from "../hooks/useApi";
import { useMutation } from "../hooks/useMutation";
import { api } from "../services/api";
import { number } from "../lib/utils";
import type {
  BatchRun,
  Dataset,
  Rule,
  SavedPrompt,
  TestCase,
} from "../types/platform";
export function RegressionTests() {
  const datasets = useApi<Dataset[]>("/datasets"),
    runs = useApi<BatchRun[]>("/dataset-runs"),
    prompts = useApi<SavedPrompt[]>("/prompts");
  const [selected, setSelected] = useState(""),
    [name, setName] = useState(""),
    [question, setQuestion] = useState(""),
    [expected, setExpected] = useState(""),
    [answer, setAnswer] = useState(""),
    [contexts, setContexts] = useState(""),
    [rules, setRules] = useState<Rule[]>([{ kind: "non_empty" }]),
    [mode, setMode] = useState<"stored" | "generate" | "rag">("stored"),
    [model, setModel] = useState(""),
    [promptId, setPromptId] = useState(""),
    [baseline, setBaseline] = useState(""),
    [minScore, setMinScore] = useState(0.8),
    [drop, setDrop] = useState(0.05),
    [latency, setLatency] = useState(0.5);
  const cases = useApi<TestCase[]>(
    selected ? `/datasets/${selected}/cases` : null,
  );
  const create = useMutation<Dataset>(),
    add = useMutation<TestCase>(),
    run = useMutation<BatchRun>(),
    gate = useMutation<unknown>(),
    detail = useMutation<BatchRun>();
  async function refresh() {
    void datasets.refresh();
    void runs.refresh();
    if (selected) void cases.refresh();
  }
  return (
    <>
      <PageHeading
        eyebrow="TEST BEFORE RELEASE"
        title="Regression tests"
        description="Create test datasets, record baselines, and catch changes before release."
      />
      <div className="platform-grid">
        <section className="panel">
          <PanelTitle title="Evaluation datasets" />
          <div className="form-body">
            <label>
              Selected dataset
              <select
                value={selected}
                onChange={(e) => {
                  setSelected(e.target.value);
                  setBaseline("");
                }}
              >
                <option value="">Choose a dataset</option>
                {datasets.data?.map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.name}
                  </option>
                ))}
              </select>
            </label>
            <form
              className="inline-form"
              onSubmit={(e) => {
                e.preventDefault();
                void create.execute(
                  async () => {
                    const d = (
                      await api.post<Dataset>("/datasets", {
                        name,
                        description: "",
                      })
                    ).data;
                    setSelected(d.id);
                    return d;
                  },
                  "Dataset created",
                  datasets.refresh,
                );
              }}
            >
              <label>
                New dataset name
                <input
                  required
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                />
              </label>
              <ActionButton busy={create.busy}>Create dataset</ActionButton>
            </form>
            <MutationError error={create.error} />
          </div>
        </section>
        <Note title="What a baseline protects">
          A baseline records a known run of the same cases and rules. New runs
          fail if quality drops, errors rise, or latency crosses your configured
          limit. Changed datasets require a new baseline.
        </Note>
      </div>
      {selected && (
        <>
          <div className="platform-grid section-gap">
            <section className="panel">
              <PanelTitle
                title="Add a test case"
                description="Stored-response mode can run without a model."
              />
              <form
                className="form-body"
                onSubmit={(e) => {
                  e.preventDefault();
                  void add.execute(
                    async () =>
                      (
                        await api.post(`/datasets/${selected}/cases`, {
                          question,
                          expected: expected || null,
                          response: answer,
                          contexts: splitList(contexts),
                          checks: rules,
                        })
                      ).data,
                    "Case added",
                    cases.refresh,
                  );
                }}
              >
                <label>
                  Question
                  <textarea
                    required
                    rows={3}
                    value={question}
                    onChange={(e) => setQuestion(e.target.value)}
                  />
                </label>
                <label>
                  Expected answer (optional)
                  <textarea
                    rows={2}
                    value={expected}
                    onChange={(e) => setExpected(e.target.value)}
                  />
                </label>
                <label>
                  Stored response
                  <textarea
                    rows={3}
                    value={answer}
                    onChange={(e) => setAnswer(e.target.value)}
                  />
                </label>
                <label>
                  Reference contexts (one per line)
                  <textarea
                    rows={2}
                    value={contexts}
                    onChange={(e) => setContexts(e.target.value)}
                  />
                </label>
                <RulesEditor value={rules} onChange={setRules} />
                <MutationError error={add.error} />
                <ActionButton busy={add.busy} disabled={!rules.length}>
                  Add case
                </ActionButton>
              </form>
            </section>
            <div>
              <section className="panel">
                <PanelTitle title="Run dataset" />
                <form
                  className="form-body"
                  onSubmit={(e) => {
                    e.preventDefault();
                    void run.execute(
                      async () =>
                        (
                          await api.post(`/datasets/${selected}/run`, {
                            mode,
                            model,
                            prompt_id: promptId || null,
                            template: "{question}",
                            threshold: 1,
                            seed: 42,
                          })
                        ).data,
                      "Dataset run saved",
                      refresh,
                    );
                  }}
                >
                  <label>
                    Execution mode
                    <select
                      value={mode}
                      onChange={(e) => setMode(e.target.value as typeof mode)}
                    >
                      <option value="stored">Evaluate stored responses</option>
                      <option value="generate">Generate fresh responses</option>
                      <option value="rag">
                        Generate with knowledge retrieval
                      </option>
                    </select>
                  </label>
                  {mode !== "stored" && (
                    <>
                      <ModelPicker value={model} onChange={setModel} />
                      <label>
                        Saved prompt version
                        <select
                          value={promptId}
                          onChange={(e) => setPromptId(e.target.value)}
                        >
                          <option value="">Default question prompt</option>
                          {prompts.data?.map((p) => (
                            <option key={p.id} value={p.id}>
                              {p.name} v{p.version}
                            </option>
                          ))}
                        </select>
                      </label>
                    </>
                  )}
                  <MutationError error={run.error} />
                  <ActionButton busy={run.busy}>Run all cases</ActionButton>
                  {run.result && (
                    <div className="run-result">
                      <Badge good={run.result.passed}>
                        {run.result.passed ? "Passed" : "Failed"}
                      </Badge>
                      <strong>{number(run.result.score * 100, 1)}%</strong>
                      <Inspect value={run.result} />
                    </div>
                  )}
                </form>
              </section>
              <section className="panel section-gap">
                <PanelTitle title="Quality gate baseline" />
                <form
                  className="form-body"
                  onSubmit={(e) => {
                    e.preventDefault();
                    void gate.execute(
                      async () =>
                        (
                          await api.put(`/datasets/${selected}/baseline`, {
                            baseline_id: baseline,
                            min_score: minScore,
                            max_score_drop: drop,
                            max_latency_increase: latency,
                            max_errors: 0,
                          })
                        ).data,
                      "Baseline saved",
                    );
                  }}
                >
                  <label>
                    Baseline run
                    <select
                      required
                      value={baseline}
                      onChange={(e) => setBaseline(e.target.value)}
                    >
                      <option value="">Select a completed run</option>
                      {runs.data
                        ?.filter(
                          (r) => r.dataset_id === selected && r.errors === 0,
                        )
                        .map((r) => (
                          <option value={r.id} key={r.id}>
                            {r.id.slice(0, 8)} · {number(r.score * 100)}%
                          </option>
                        ))}
                    </select>
                  </label>
                  <div className="form-row">
                    <label>
                      Minimum score (0–1)
                      <input
                        type="number"
                        step="0.05"
                        min="0"
                        max="1"
                        value={minScore}
                        onChange={(e) => setMinScore(+e.target.value)}
                      />
                    </label>
                    <label>
                      Maximum score drop
                      <input
                        type="number"
                        step="0.01"
                        min="0"
                        max="1"
                        value={drop}
                        onChange={(e) => setDrop(+e.target.value)}
                      />
                    </label>
                  </div>
                  <label>
                    Maximum latency increase (0.5 = 50%)
                    <input
                      type="number"
                      step="0.1"
                      min="0"
                      max="10"
                      value={latency}
                      onChange={(e) => setLatency(+e.target.value)}
                    />
                  </label>
                  <MutationError error={gate.error} />
                  <ActionButton busy={gate.busy}>
                    Save baseline & thresholds
                  </ActionButton>
                </form>
              </section>
            </div>
          </div>
          <section className="panel section-gap">
            <PanelTitle title={`Cases · ${cases.data?.length ?? 0}`} />
            <div className="record-list">
              {cases.data?.map((c) => (
                <div key={c.id} className="record-item">
                  <h3>{c.question}</h3>
                  <Inspect value={c} />
                </div>
              ))}
              {cases.data?.length === 0 && (
                <p className="muted-text">Add your first case above.</p>
              )}
            </div>
          </section>
        </>
      )}
      <DataPanel
        title="Dataset run history"
        query={runs}
        render={(r) => (
          <>
            <div className="record-heading">
              <h3>
                {datasets.data?.find((d) => d.id === r.dataset_id)?.name ??
                  r.dataset_id.slice(0, 8)}
              </h3>
              <Badge good={r.passed}>{r.passed ? "Passed" : "Failed"}</Badge>
              <strong>{number(r.score * 100)}%</strong>
              <span>
                {number(r.latency_ms)} ms · {r.errors} errors
              </span>
              <Button
                size="sm"
                variant="outline"
                onClick={() =>
                  void detail.execute(
                    async () => (await api.get(`/dataset-runs/${r.id}`)).data,
                    "Results loaded",
                  )
                }
              >
                Inspect cases
              </Button>
            </div>
            <Inspect value={r.gate?.reason ? r.gate : r.configuration} />
          </>
        )}
      />
      {detail.result && (
        <section className="panel section-gap">
          <PanelTitle
            title={`Case results · ${detail.result.id.slice(0, 8)}`}
          />
          <div className="form-body">
            <Inspect label="Full run and case results" value={detail.result} />
          </div>
        </section>
      )}
    </>
  );
}
