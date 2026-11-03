import { useState } from "react";
import { Link } from "react-router-dom";
import {
  ArrowRight,
  Copy,
  Loader2,
  Play,
  Settings2,
  SquareTerminal,
} from "lucide-react";
import { toast } from "sonner";
import {
  Badge,
  Empty,
  ErrorState,
  PageHeading,
  PanelTitle,
} from "../components/common";
import { Button } from "../components/ui/button";
import { useApi } from "../hooks/useApi";
import type { SavedPrompt } from "../types/platform";
import { useModels } from "../contexts/ModelsContext";
import { api, errorMessage } from "../services/api";
import { number } from "../lib/utils";
import type { Trace } from "../types";
export function Playground() {
  const models = useModels();
  const saved = useApi<SavedPrompt[]>("/prompts");
  const [promptName, setPromptName] = useState("");
  const [saving, setSaving] = useState(false);
  async function savePrompt() {
    setSaving(true);
    try {
      await api.post("/prompts", {
        name: promptName,
        system,
        template: prompt,
        configuration: {
          model: model || models.data?.models[0]?.name,
          temperature,
          max_tokens: maxTokens,
        },
      });
      toast.success("Prompt version saved");
      void saved.refresh();
    } catch (e) {
      toast.error(errorMessage(e));
    } finally {
      setSaving(false);
    }
  }
  const [model, setModel] = useState(""),
    [system, setSystem] = useState(""),
    [prompt, setPrompt] = useState(""),
    [temperature, setTemperature] = useState(0.2),
    [maxTokens, setMaxTokens] = useState(512),
    [busy, setBusy] = useState(false),
    [result, setResult] = useState<Trace | null>(null),
    [error, setError] = useState<string | null>(null);
  async function run() {
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const { data } = await api.post<Trace>("/playground/generate", {
        model: model || models.data?.models[0]?.name,
        system,
        prompt,
        temperature,
        max_tokens: maxTokens,
      });
      setResult(data);
      toast.success("Response generated and trace saved");
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <PageHeading
        eyebrow="BUILD & EXPLORE"
        title="AI Playground"
        description="Give your local model a prompt. See exactly what comes back."
        action={<Badge>Local inference</Badge>}
      />
      {(models.error ||
        models.data?.available === false ||
        models.data?.models.length === 0) && (
        <div className="info-banner">
          <SquareTerminal size={20} />
          <div>
            <strong>
              {models.data?.available
                ? "No models installed"
                : "Ollama is not connected"}
            </strong>
            <p>
              Open Settings for model installation instructions. You can
              evaluate existing responses without a model.
            </p>
          </div>
          <Button asChild variant="outline">
            <Link to="/settings">
              Settings
              <ArrowRight size={14} />
            </Link>
          </Button>
        </div>
      )}
      <div className="playground-grid">
        <section className="panel prompt-panel">
          <PanelTitle
            title="Prompt configuration"
            description="Start with a clear task and explicit instructions."
            action={<Settings2 size={17} />}
          />
          <form
            onSubmit={(e) => {
              e.preventDefault();
              void run();
            }}
            className="form-body"
          >
            <label>
              Saved prompt version
              <select
                defaultValue=""
                onChange={(e) => {
                  const p = saved.data?.find((v) => v.id === e.target.value);
                  if (p) {
                    setPromptName(p.name);
                    setSystem(p.system);
                    setPrompt(p.template);
                    const c = p.configuration;
                    if (typeof c.temperature === "number")
                      setTemperature(c.temperature);
                    if (typeof c.max_tokens === "number")
                      setMaxTokens(c.max_tokens);
                    if (typeof c.model === "string") setModel(c.model);
                  }
                }}
              >
                <option value="">Start from scratch</option>
                {saved.data?.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name} · v{p.version}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Model
              <select
                value={model || models.data?.models[0]?.name || ""}
                onChange={(e) => setModel(e.target.value)}
                disabled={!models.data?.models.length}
              >
                <option value="" disabled>
                  Select a local model
                </option>
                {models.data?.models.map((m) => (
                  <option key={m.name}>{m.name}</option>
                ))}
              </select>
            </label>
            <label>
              System instructions <span className="label-note">optional</span>
              <textarea
                rows={4}
                value={system}
                onChange={(e) => setSystem(e.target.value)}
                maxLength={16000}
                placeholder="You are a helpful assistant. Be concise and cite your sources when available."
              />
            </label>
            <label>
              Your prompt
              <textarea
                rows={7}
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                required
                maxLength={32000}
                placeholder="What would you like to ask your model?"
              />
            </label>
            <div className="form-row">
              <label>
                Temperature
                <input
                  type="number"
                  step="0.1"
                  min="0"
                  max="2"
                  value={temperature}
                  onChange={(e) => setTemperature(+e.target.value)}
                  required
                />
                <small>Lower values produce more consistent output.</small>
              </label>
              <label>
                Maximum output tokens
                <input
                  type="number"
                  min="1"
                  max="8192"
                  value={maxTokens}
                  onChange={(e) => setMaxTokens(+e.target.value)}
                  required
                />
                <small>Caps the length of the generated response.</small>
              </label>
            </div>
            <label>
              Prompt version name
              <input
                value={promptName}
                onChange={(e) => setPromptName(e.target.value)}
                placeholder="support-assistant"
              />
            </label>
            <Button
              type="button"
              variant="outline"
              disabled={saving || !promptName.trim() || !prompt.trim()}
              onClick={() => void savePrompt()}
            >
              {saving ? "Saving…" : "Save prompt as a new version"}
            </Button>
            <Button
              type="submit"
              disabled={busy || !prompt.trim() || !models.data?.models.length}
            >
              {busy ? (
                <Loader2 className="animate-spin" size={16} />
              ) : (
                <Play size={16} />
              )}{" "}
              {busy ? "Generating…" : "Run prompt"}
            </Button>
          </form>
        </section>
        <section className="panel response-panel">
          <PanelTitle
            title="Model response"
            description="Output, usage, and timing from the actual request."
            action={
              result && (
                <Button
                  variant="ghost"
                  size="icon"
                  aria-label="Copy response"
                  onClick={() =>
                    void navigator.clipboard
                      .writeText(result.response || "")
                      .then(() => toast.success("Response copied"))
                      .catch(() => toast.error("Could not access clipboard"))
                  }
                >
                  <Copy size={16} />
                </Button>
              )
            }
          />
          {error && <ErrorState message={error} retry={run} />}{" "}
          {busy ? (
            <div className="empty">
              <Loader2 size={25} className="animate-spin" />
              <h3>Your model is working</h3>
              <p>
                The first request may take longer while Ollama loads the model.
              </p>
            </div>
          ) : result ? (
            <div className="response-content">
              <div className="response-meta">
                <Badge good>{result.model}</Badge>
                <span>{number(result.latency_ms / 1000, 2)}s</span>
                <span>
                  {number(result.input_tokens)} in /{" "}
                  {number(result.output_tokens)} out
                </span>
              </div>
              <pre>{result.response}</pre>
              <Button variant="outline" asChild>
                <Link
                  to="/evaluations"
                  state={{ response: result.response, trace_id: result.id }}
                >
                  Evaluate this response
                  <ArrowRight size={15} />
                </Link>
              </Button>
              <Link to="/traces" className="text-link">
                Inspect request trace
                <ArrowRight size={14} />
              </Link>
            </div>
          ) : (
            !error && (
              <Empty title="A blank canvas for your next idea">
                Choose a model, write a prompt,
                <br />
                and run your first request.
              </Empty>
            )
          )}
        </section>
      </div>
    </>
  );
}
