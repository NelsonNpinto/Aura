import { useState } from "react";
import { Badge, PageHeading, PanelTitle } from "../components/common";
import {
  ActionButton,
  DataPanel,
  Inspect,
  ModelPicker,
  MutationError,
  Note,
} from "../components/platform";
import { Button } from "../components/ui/button";
import { useApi } from "../hooks/useApi";
import { useMutation } from "../hooks/useMutation";
import { api } from "../services/api";
import { number } from "../lib/utils";
import type {
  Dataset,
  Experiment,
  RunConfig,
  SavedPrompt,
} from "../types/platform";
const fresh: RunConfig = {
  mode: "generate",
  model: "",
  temperature: 0.2,
  template: "{question}",
  max_tokens: 256,
  seed: 42,
  threshold: 1,
  retrieval: "hybrid",
  top_k: 4,
};
export function Experiments() {
  const datasets = useApi<Dataset[]>("/datasets"),
    prompts = useApi<SavedPrompt[]>("/prompts"),
    history = useApi<Experiment[]>("/experiments"),
    action = useMutation<Experiment>();
  const [name, setName] = useState(""),
    [dataset, setDataset] = useState(""),
    [judgeModel, setJudgeModel] = useState(""),
    [configs, setConfigs] = useState<RunConfig[]>([{ ...fresh }, { ...fresh }]);
  const update = (i: number, patch: Partial<RunConfig>) =>
    setConfigs((v) => v.map((c, n) => (n === i ? { ...c, ...patch } : c)));
  const show = (r: Experiment) => (
    <>
      <h3>{r.name}</h3>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Configuration</th>
              <th>Check score</th>
              <th>Latency</th>
              <th>Tokens in / out</th>
              <th>Faithfulness / relevance</th>
              <th>Errors</th>
              <th>Gate</th>
            </tr>
          </thead>
          <tbody>
            {r.results.map((c, i) => (
              <tr key={i}>
                <td>
                  {c.configuration.model || "Stored responses"}
                  <small>
                    Temperature {c.configuration.temperature} ·{" "}
                    {c.configuration.mode}
                  </small>
                </td>
                <td>{number(c.score * 100, 1)}%</td>
                <td>{number(c.latency_ms)} ms</td>
                <td>
                  {number(c.metrics?.input_tokens)} /{" "}
                  {number(c.metrics?.output_tokens)}
                </td>
                <td>
                  {c.metrics?.faithfulness == null
                    ? "—"
                    : `${number(c.metrics.faithfulness * 100)}%`}{" "}
                  /{" "}
                  {c.metrics?.answer_relevance == null
                    ? "—"
                    : `${number(c.metrics.answer_relevance * 100)}%`}
                </td>
                <td>{c.errors}</td>
                <td>
                  <Badge good={c.passed}>{c.passed ? "Pass" : "Fail"}</Badge>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <Inspect value={r} />
    </>
  );
  return (
    <>
      <PageHeading
        eyebrow="REPRODUCIBLE COMPARISONS"
        title="Experiments"
        description="Compare models, prompt versions, temperature, and retrieval on the same cases."
      />
      <section className="panel">
        <PanelTitle
          title="Configure an experiment"
          description="Two to five configurations. Generation uses local models only."
        />
        <form
          className="form-body"
          onSubmit={(e) => {
            e.preventDefault();
            void action.execute(
              async () =>
                (
                  await api.post(
                    "/experiments",
                    {
                      name,
                      dataset_id: dataset,
                      configurations: configs.map((c) => ({
                        ...c,
                        judge_model: judgeModel,
                      })),
                    },
                    { timeout: 0 },
                  )
                ).data,
              "Experiment complete",
              history.refresh,
            );
          }}
        >
          <div className="form-row">
            <label>
              Experiment name
              <input
                required
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
            </label>
            <label>
              Dataset
              <select
                required
                value={dataset}
                onChange={(e) => setDataset(e.target.value)}
              >
                <option value="">Select a dataset</option>
                {datasets.data?.map((d) => (
                  <option value={d.id} key={d.id}>
                    {d.name}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <label>
            Optional judge model
            <input
              value={judgeModel}
              onChange={(e) => setJudgeModel(e.target.value)}
              placeholder="Leave blank for deterministic checks only"
            />
            <small>
              Use an installed model name to measure quality, faithfulness, and
              relevance. This adds an evaluation request for each answer.
            </small>
          </label>
          <div className="config-grid">
            {configs.map((c, i) => (
              <div className="config-card" key={i}>
                <h3>Configuration {i + 1}</h3>
                <ModelPicker
                  value={c.model}
                  onChange={(v) => update(i, { model: v })}
                />
                <label>
                  Mode
                  <select
                    value={c.mode}
                    onChange={(e) =>
                      update(i, { mode: e.target.value as RunConfig["mode"] })
                    }
                  >
                    <option value="generate">Direct generation</option>
                    <option value="rag">RAG generation</option>
                  </select>
                </label>
                <label>
                  Prompt version
                  <select
                    value={c.prompt_id ?? ""}
                    onChange={(e) =>
                      update(i, { prompt_id: e.target.value || undefined })
                    }
                  >
                    <option value="">Default question</option>
                    {prompts.data?.map((p) => (
                      <option value={p.id} key={p.id}>
                        {p.name} v{p.version}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  Temperature
                  <input
                    type="number"
                    min="0"
                    max="2"
                    step="0.1"
                    value={c.temperature}
                    onChange={(e) =>
                      update(i, { temperature: +e.target.value })
                    }
                  />
                </label>
                {c.mode === "rag" && (
                  <>
                    <label>
                      Retrieval
                      <select
                        value={c.retrieval}
                        onChange={(e) =>
                          update(i, {
                            retrieval: e.target.value as RunConfig["retrieval"],
                          })
                        }
                      >
                        <option value="hybrid">Hybrid</option>
                        <option value="bm25">BM25</option>
                        <option value="vector">Vector</option>
                      </select>
                    </label>
                    <label>
                      Top chunks
                      <input
                        type="number"
                        min="1"
                        max="10"
                        value={c.top_k}
                        onChange={(e) => update(i, { top_k: +e.target.value })}
                      />
                    </label>
                  </>
                )}
                {configs.length > 2 && (
                  <Button
                    type="button"
                    variant="ghost"
                    onClick={() =>
                      setConfigs((v) => v.filter((_, n) => n !== i))
                    }
                  >
                    Remove configuration
                  </Button>
                )}
              </div>
            ))}
          </div>
          {configs.length < 5 && (
            <Button
              type="button"
              variant="outline"
              onClick={() => setConfigs((v) => [...v, { ...fresh }])}
            >
              Add configuration
            </Button>
          )}
          <MutationError error={action.error} />
          <ActionButton busy={action.busy}>Run experiment</ActionButton>
        </form>
      </section>
      <Note title="Compare like with like">
        Scores here measure deterministic output checks on the same dataset.
        Review actual responses and model-based judgments before drawing
        conclusions about factual quality. The saved configuration includes
        prompt version, seed, token limit, and retrieval settings.
      </Note>
      {action.result && (
        <section className="panel section-gap">
          <PanelTitle title="Latest comparison" />
          <div className="form-body">{show(action.result)}</div>
        </section>
      )}
      <DataPanel title="Experiment history" query={history} render={show} />
    </>
  );
}
