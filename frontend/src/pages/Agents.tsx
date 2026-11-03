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
} from "../components/platform";
import { useApi } from "../hooks/useApi";
import { useMutation } from "../hooks/useMutation";
import { api } from "../services/api";
import type { AgentRun, Rule } from "../types/platform";
export function Agents() {
  const history = useApi<AgentRun[]>("/agents/runs"),
    action = useMutation<AgentRun>();
  const [task, setTask] = useState(""),
    [model, setModel] = useState(""),
    [expected, setExpected] = useState(""),
    [argumentsJson, setArgumentsJson] = useState("[]"),
    [rules, setRules] = useState<Rule[]>([{ kind: "non_empty" }]),
    [steps, setSteps] = useState(4);
  const show = (r: AgentRun) => (
    <>
      <div className="record-heading">
        <h3>{r.task}</h3>
        <Badge good={r.passed}>
          {r.passed ? "Checks passed" : "Checks failed"}
        </Badge>
      </div>
      <pre>{r.response || "(no final answer)"}</pre>
      <div className="agent-timeline">
        {r.steps.map((s, i) => (
          <div key={i}>
            <span className="step-number">{i + 1}</span>
            <div>
              <h3>{s.tool ?? "Model planning error"}</h3>
              <code>{JSON.stringify(s.arguments ?? {})}</code>
              {s.error ? (
                <p className="inline-error">{s.error}</p>
              ) : (
                <pre>{s.result}</pre>
              )}
              <small>Trace {s.trace_id.slice(0, 8)}</small>
            </div>
          </div>
        ))}
      </div>
      <Inspect
        label="Evaluation metrics and expected tool path"
        value={r.metrics}
      />
    </>
  );
  return (
    <>
      <PageHeading
        eyebrow="TOOL USE & TASKS"
        title="Agent evaluation"
        description="Run a bounded LangGraph agent and inspect every tool choice."
      />
      <div className="platform-grid">
        <section className="panel">
          <PanelTitle title="Run an agent task" />
          <form
            className="form-body"
            onSubmit={(e) => {
              e.preventDefault();
              void action.execute(
                async () =>
                  (
                    await api.post(
                      "/agents/runs",
                      {
                        task,
                        model,
                        expected_tools: expected
                          .split(",")
                          .map((v) => v.trim())
                          .filter(Boolean),
                        expected_arguments: JSON.parse(argumentsJson),
                        checks: rules,
                        max_steps: steps,
                      },
                      { timeout: 0 },
                    )
                  ).data,
                "Agent run saved",
                history.refresh,
              );
            }}
          >
            <ModelPicker value={model} onChange={setModel} />
            <label>
              Task
              <textarea
                required
                rows={4}
                value={task}
                onChange={(e) => setTask(e.target.value)}
                placeholder="Calculate 19 * 7, then tell me the result."
              />
            </label>
            <label>
              Expected tool sequence (comma-separated)
              <input
                value={expected}
                onChange={(e) => setExpected(e.target.value)}
                placeholder="calculator, knowledge_search"
              />
              <small>
                Available: calculator, knowledge_search, customer_lookup
              </small>
            </label>
            <label>
              Expected argument objects (optional JSON array)
              <textarea
                rows={3}
                value={argumentsJson}
                onChange={(e) => setArgumentsJson(e.target.value)}
                placeholder={'[{"expression":"19 * 7"}]'}
              />
            </label>
            <label>
              Maximum tool steps
              <input
                type="number"
                min="1"
                max="5"
                value={steps}
                onChange={(e) => setSteps(+e.target.value)}
              />
            </label>
            <RulesEditor value={rules} onChange={setRules} />
            <MutationError error={action.error} />
            <ActionButton busy={action.busy} disabled={!rules.length}>
              Run agent
            </ActionButton>
          </form>
        </section>
        <div>
          {action.result ? (
            <section className="panel">
              <PanelTitle title="Agent trace" />
              <div className="form-body">{show(action.result)}</div>
            </section>
          ) : (
            <Note title="Three tools, a bounded workflow">
              The calculator supports arithmetic only. Knowledge search uses
              your uploaded documents. Customer lookup uses clearly marked mock
              IDs demo-001 and demo-002. No external customer system or
              financial action is connected.
            </Note>
          )}
          <Note title="Task completion needs evidence">
            A final answer and passing rules are useful checks, but do not prove
            semantic task success. Supply an expected tool sequence, expected
            arguments, and exact answer checks when you need stronger
            verification.
          </Note>
        </div>
      </div>
      <DataPanel title="Agent run history" query={history} render={show} />
    </>
  );
}
