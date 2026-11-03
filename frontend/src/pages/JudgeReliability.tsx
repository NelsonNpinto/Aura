import { useState } from "react";
import { Badge, Empty, PageHeading, PanelTitle } from "../components/common";
import {
  ActionButton,
  Inspect,
  MutationError,
  Note,
} from "../components/platform";
import { useApi } from "../hooks/useApi";
import { useMutation } from "../hooks/useMutation";
import { api } from "../services/api";
import { number } from "../lib/utils";
import type { JudgeReview, Reliability } from "../types/platform";
export function JudgeReliability() {
  const reviews = useApi<JudgeReview[]>("/judge/reviews"),
    report = useApi<Reliability>("/judge/reliability");
  const [id, setId] = useState(""),
    [reviewer, setReviewer] = useState(""),
    [passed, setPassed] = useState(false),
    [score, setScore] = useState(0.5),
    [feedback, setFeedback] = useState("");
  const action = useMutation<unknown>(),
    row = reviews.data?.find((r) => r.id === id);
  return (
    <>
      <PageHeading
        eyebrow="CALIBRATE YOUR EVALUATOR"
        title="Judge Reliability"
        description="Compare judge decisions with explicit human ratings."
      />
      <div className="metric-grid">
        {[
          {
            label: "Paired human labels",
            value: number(report.data?.sample_size),
          },
          {
            label: "Observed agreement",
            value:
              report.data?.agreement == null
                ? "—"
                : `${number(report.data.agreement * 100, 1)}%`,
          },
          { label: "Cohen’s kappa", value: number(report.data?.kappa, 3) },
          {
            label: "Mean score error",
            value: number(report.data?.mean_absolute_score_error, 3),
          },
        ].map((m) => (
          <div className="metric-card" key={m.label}>
            <div>{m.label}</div>
            <strong>{m.value}</strong>
            <p>Computed from saved paired reviews</p>
          </div>
        ))}
      </div>
      <div className="platform-grid">
        <section className="panel">
          <PanelTitle
            title="Add a human rating"
            description="One current human consensus rating per judge review."
          />
          <form
            className="form-body"
            onSubmit={(e) => {
              e.preventDefault();
              void action.execute(
                async () =>
                  (
                    await api.put(`/judge/reviews/${id}/human`, {
                      reviewer,
                      passed,
                      score,
                      feedback,
                    })
                  ).data,
                "Human rating saved",
                report.refresh,
              );
            }}
          >
            <label>
              Judge review
              <select
                required
                value={id}
                onChange={(e) => setId(e.target.value)}
              >
                <option value="">Choose a valid judgment</option>
                {reviews.data
                  ?.filter((r) => !r.error && r.passed != null)
                  .map((r) => (
                    <option value={r.id} key={r.id}>
                      {r.question.slice(0, 65)} · {r.id.slice(0, 6)}
                    </option>
                  ))}
              </select>
            </label>
            {row && (
              <>
                <h3>{row.question}</h3>
                <pre>{row.response}</pre>
                <Badge good={row.passed ?? undefined}>
                  AI decision: {row.passed ? "Pass" : "Fail"} ·{" "}
                  {number((row.score ?? 0) * 100)}%
                </Badge>
                <Inspect value={row.verdict} />
              </>
            )}
            <label>
              Reviewer / consensus group
              <input
                required
                value={reviewer}
                maxLength={100}
                onChange={(e) => setReviewer(e.target.value)}
              />
            </label>
            <label>
              Human score (0–1)
              <input
                type="number"
                step="0.05"
                min="0"
                max="1"
                value={score}
                onChange={(e) => setScore(+e.target.value)}
              />
            </label>
            <label>
              Human decision
              <select
                value={passed ? "pass" : "fail"}
                onChange={(e) => setPassed(e.target.value === "pass")}
              >
                <option value="fail">Fail</option>
                <option value="pass">Pass</option>
              </select>
            </label>
            <label>
              Explanation
              <textarea
                rows={4}
                value={feedback}
                onChange={(e) => setFeedback(e.target.value)}
              />
            </label>
            <MutationError error={action.error} />
            <ActionButton busy={action.busy} disabled={!id}>
              Save human rating
            </ActionButton>
          </form>
        </section>
        <div>
          <section className="panel">
            <PanelTitle title="Agreement report" />
            {report.data?.sample_size ? (
              <div className="form-body">
                <p>{report.data.message}</p>
                <h3>False passes · {report.data.false_passes.length}</h3>
                <p className="muted-text">Judge passed; human failed.</p>
                <pre>
                  {report.data.false_passes.join("\n") || "None in this sample"}
                </pre>
                <h3>False fails · {report.data.false_fails.length}</h3>
                <p className="muted-text">Judge failed; human passed.</p>
                <pre>
                  {report.data.false_fails.join("\n") || "None in this sample"}
                </pre>
              </div>
            ) : (
              <Empty title="No reliability claim without labels">
                Add human ratings to start measuring agreement.
              </Empty>
            )}
          </section>
          <Note title="Read these numbers carefully">
            Kappa adjusts agreement for chance. It is undefined when both label
            distributions contain only one class. A small or unrepresentative
            sample cannot establish judge reliability. Use consistent rubrics
            and label definitions across the sample.
          </Note>
        </div>
      </div>
    </>
  );
}
