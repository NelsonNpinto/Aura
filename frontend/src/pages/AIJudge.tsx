import { useState } from "react";
import { Badge, PageHeading, PanelTitle } from "../components/common";
import {
  ActionButton,
  DataPanel,
  Inspect,
  ModelPicker,
  MutationError,
  Note,
  splitList,
} from "../components/platform";
import { useApi } from "../hooks/useApi";
import { useMutation } from "../hooks/useMutation";
import { api } from "../services/api";
import { number } from "../lib/utils";
import type { JudgeReview } from "../types/platform";
export function AIJudge() {
  const history = useApi<JudgeReview[]>("/judge/reviews"),
    action = useMutation<JudgeReview>();
  const [model, setModel] = useState(""),
    [question, setQuestion] = useState(""),
    [expected, setExpected] = useState(""),
    [response, setResponse] = useState(""),
    [contexts, setContexts] = useState(""),
    [rubric, setRubric] = useState(
      "Assess evidence, acknowledge uncertainty, and explain each score.",
    ),
    [threshold, setThreshold] = useState(0.7),
    [engine, setEngine] = useState("local_judge");
  function verdict(row: JudgeReview) {
    return (
      <>
        <div className="record-heading">
          <h3>{row.question}</h3>
          <Badge good={row.passed ?? undefined}>
            {row.error
              ? "Invalid judgment"
              : row.passed == null
                ? "Unscored"
                : row.passed
                  ? "Passed"
                  : "Failed"}
          </Badge>
          <strong>
            {row.score == null ? "—" : `${number(row.score * 100, 1)}%`}
          </strong>
          <Badge>{row.engine}</Badge>
        </div>
        {row.error ? (
          <div className="inline-error">{row.error}</div>
        ) : (
          <div className="judge-dimensions">
            {Object.entries(row.verdict).map(([key, v]) =>
              typeof v === "object" &&
              v !== null &&
              !Array.isArray(v) &&
              "score" in v ? (
                <div key={key}>
                  <span>{key}</span>
                  <strong>
                    {v.score == null ? "—" : number((v.score as number) * 100)}%
                  </strong>
                  <p>{(v as { explanation: string }).explanation}</p>
                </div>
              ) : key === "unsupported_claims" && Array.isArray(v) ? (
                <div key={key}>
                  <span>Unsupported claims</span>
                  <p>
                    {v.length ? v.join("; ") : "None identified by this judge"}
                  </p>
                </div>
              ) : null,
            )}
          </div>
        )}
        <Inspect
          value={{
            verdict: row.verdict,
            configuration: row.configuration,
            response: row.response,
            contexts: row.contexts,
          }}
        />
      </>
    );
  }
  return (
    <>
      <PageHeading
        eyebrow="MODEL-BASED EVALUATION"
        title="AI Judge"
        description="Score responses using a defined rubric and local model judgments."
      />
      <div className="info-banner">
        <p>
          These are model estimates. A valid JSON judgment can still be wrong.
          Calibrate against human ratings in Judge Reliability.
        </p>
      </div>
      <div className="platform-grid">
        <section className="panel">
          <PanelTitle title="Create a judgment" />
          <form
            className="form-body"
            onSubmit={(e) => {
              e.preventDefault();
              void action.execute(
                async () =>
                  (
                    await api.post(
                      "/judge/reviews",
                      {
                        model,
                        question,
                        expected: expected || null,
                        response,
                        contexts: splitList(contexts),
                        rubric,
                        threshold,
                        engine,
                      },
                      { timeout: 1200000 },
                    )
                  ).data,
                "Judgment stored",
                history.refresh,
              );
            }}
          >
            <ModelPicker value={model} onChange={setModel} />
            <label>
              Scoring engine
              <select
                value={engine}
                onChange={(e) => setEngine(e.target.value)}
              >
                <option value="local_judge">Local rubric judge</option>
                <option value="ragas">
                  RAGAS · faithfulness, relevance, context precision/recall
                </option>
              </select>
            </label>
            <label>
              Question
              <textarea
                required
                rows={2}
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
              />
            </label>
            <label>
              Reference answer
              <textarea
                rows={2}
                required={engine === "ragas"}
                value={expected}
                onChange={(e) => setExpected(e.target.value)}
              />
            </label>
            <label>
              Generated response
              <textarea
                rows={4}
                value={response}
                onChange={(e) => setResponse(e.target.value)}
              />
            </label>
            <label>
              Reference contexts (one per line)
              <textarea
                rows={3}
                required={engine === "ragas"}
                value={contexts}
                onChange={(e) => setContexts(e.target.value)}
              />
            </label>
            <label>
              Evaluation rubric
              <textarea
                rows={3}
                value={rubric}
                onChange={(e) => setRubric(e.target.value)}
              />
            </label>
            <label>
              Pass threshold (0–1)
              <input
                type="number"
                step="0.05"
                min="0"
                max="1"
                value={threshold}
                onChange={(e) => setThreshold(+e.target.value)}
              />
            </label>
            <MutationError error={action.error} />
            <ActionButton busy={action.busy}>Run judge</ActionButton>
          </form>
        </section>
        <div>
          {action.result ? (
            <section className="panel">
              <PanelTitle title="Latest judgment" />
              <div className="form-body">{verdict(action.result)}</div>
            </section>
          ) : (
            <Note title="Evidence makes evaluation stronger">
              Provide a reference answer and retrieved context where possible.
              The judge evaluates correctness, relevance, faithfulness,
              completeness, and clarity, and flags unsupported claims.
              Unsupported claims force a failure even when the average score
              clears the threshold.
            </Note>
          )}
          <Note title="RAGAS runs locally">
            The RAGAS adapter uses Ollama and Sentence Transformer embeddings.
            Reference-based context precision and recall require a reference
            answer. Failed or non-finite metrics remain unscored rather than
            being replaced by a passing value.
          </Note>
        </div>
      </div>
      <DataPanel
        title="Judge review history"
        query={history}
        render={verdict}
      />
    </>
  );
}
