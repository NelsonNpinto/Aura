import { useState } from "react";
import { Badge, PageHeading, PanelTitle } from "../components/common";
import {
  ActionButton,
  DataPanel,
  Inspect,
  MutationError,
  Note,
} from "../components/platform";
import { Button } from "../components/ui/button";
import { useApi } from "../hooks/useApi";
import { useMutation } from "../hooks/useMutation";
import { api } from "../services/api";
import type { SavedPrompt } from "../types/platform";
export function Prompts() {
  const history = useApi<SavedPrompt[]>("/prompts"),
    action = useMutation<SavedPrompt>();
  const [name, setName] = useState(""),
    [system, setSystem] = useState(""),
    [template, setTemplate] = useState("{question}"),
    [left, setLeft] = useState(""),
    [right, setRight] = useState("");
  const a = history.data?.find((p) => p.id === left),
    b = history.data?.find((p) => p.id === right);
  return (
    <>
      <PageHeading
        eyebrow="PROMPT MANAGEMENT"
        title="Prompt library"
        description="Save immutable prompt versions and compare their instructions."
      />
      <div className="platform-grid">
        <section className="panel">
          <PanelTitle
            title="Save a prompt version"
            description="The same name creates the next version automatically."
          />
          <form
            className="form-body"
            onSubmit={(e) => {
              e.preventDefault();
              void action.execute(
                async () =>
                  (
                    await api.post("/prompts", {
                      name,
                      system,
                      template,
                      configuration: {},
                    })
                  ).data,
                "Prompt version saved",
                history.refresh,
              );
            }}
          >
            <label>
              Name
              <input
                value={name}
                required
                maxLength={200}
                onChange={(e) => setName(e.target.value)}
              />
            </label>
            <label>
              System instructions
              <textarea
                rows={5}
                value={system}
                onChange={(e) => setSystem(e.target.value)}
              />
            </label>
            <label>
              Prompt template
              <textarea
                rows={5}
                value={template}
                required
                onChange={(e) => setTemplate(e.target.value)}
              />
              <small>
                Use {"{question}"} for the dataset question in repeatable runs.
              </small>
            </label>
            <MutationError error={action.error} />
            <ActionButton busy={action.busy}>Save new version</ActionButton>
          </form>
        </section>
        <div>
          <section className="panel">
            <PanelTitle title="Compare versions" />
            <div className="form-body">
              {[
                ["Version A", left, setLeft],
                ["Version B", right, setRight],
              ].map(([label, val, set]) => (
                <label key={label as string}>
                  {label as string}
                  <select
                    value={val as string}
                    onChange={(e) =>
                      (set as (v: string) => void)(e.target.value)
                    }
                  >
                    <option value="">Select a version</option>
                    {history.data?.map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.name} · v{p.version}
                      </option>
                    ))}
                  </select>
                </label>
              ))}
              {a && b && (
                <>
                  <Badge
                    good={a.system === b.system && a.template === b.template}
                  >
                    {a.system === b.system && a.template === b.template
                      ? "Identical instructions"
                      : "Instructions differ"}
                  </Badge>
                  <div className="compare-columns">
                    {[a, b].map((p, i) => (
                      <div key={i}>
                        <h3>
                          {p.name} · v{p.version}
                        </h3>
                        <pre>
                          {p.system}
                          {"\n\n"}
                          {p.template}
                        </pre>
                      </div>
                    ))}
                  </div>
                </>
              )}
            </div>
          </section>
          <Note title="Versioning makes changes visible">
            An older prompt is never overwritten. Choose two versions to inspect
            their instructions; use Experiments to compare their measured
            behavior on the same dataset.
          </Note>
        </div>
      </div>
      <DataPanel
        title="Saved prompt versions"
        query={history}
        render={(p) => (
          <>
            <div className="record-heading">
              <h3>{p.name}</h3>
              <Badge>v{p.version}</Badge>
              <Button
                size="sm"
                variant="outline"
                onClick={() => {
                  setName(p.name);
                  setSystem(p.system);
                  setTemplate(p.template);
                  window.scrollTo({ top: 0, behavior: "smooth" });
                }}
              >
                Edit as new version
              </Button>
            </div>
            <Inspect
              value={{
                system: p.system,
                template: p.template,
                configuration: p.configuration,
              }}
            />
          </>
        )}
      />
    </>
  );
}
