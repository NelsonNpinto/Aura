import { useState } from "react";
import { toast } from "sonner";
import { RefreshCw } from "lucide-react";
import {
  Badge,
  ErrorState,
  Loading,
  PageHeading,
  PanelTitle,
} from "../components/common";
import { Button } from "../components/ui/button";
import { useModels } from "../contexts/ModelsContext";
import { useApi } from "../hooks/useApi";
export function Settings() {
  const [apiKey, setApiKey] = useState(
    sessionStorage.getItem("aura-api-key") ?? "",
  );
  const models = useModels(),
    health = useApi<{
      status: string;
      database: string;
      database_engine: string;
    }>("/health");
  return (
    <>
      <PageHeading
        eyebrow="WORKSPACE CONFIGURATION"
        title="Settings"
        description="Your local services, models, and environment."
        action={
          <Button
            variant="outline"
            onClick={() => {
              void models.refresh();
              void health.refresh();
            }}
          >
            <RefreshCw size={15} />
            Check connections
          </Button>
        }
      />
      <section className="panel" style={{ marginBottom: 24 }}>
        <PanelTitle
          title="Workspace API access"
          description="Only needed if API_KEY is configured on the server."
        />
        <form
          className="form-body"
          onSubmit={(e) => {
            e.preventDefault();
            if (apiKey) sessionStorage.setItem("aura-api-key", apiKey);
            else sessionStorage.removeItem("aura-api-key");
            toast.success("Session API key updated");
            void models.refresh();
          }}
        >
          <label>
            API key
            <input
              type="password"
              autoComplete="off"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
            />
            <small>
              Stored for this browser session only. The webhook uses a separate
              secret.
            </small>
          </label>
          <Button type="submit">Apply session key</Button>
        </form>
      </section>
      <div className="overview-columns">
        <section className="panel">
          <PanelTitle title="Service connections" />
          <div className="signal-list">
            <div>
              <span>
                FastAPI +{" "}
                {health.data?.database_engine === "sqlite"
                  ? "SQLite (test preview)"
                  : "PostgreSQL"}
              </span>
              <Badge good={!!health.data}>
                {health.loading
                  ? "Checking"
                  : health.data
                    ? "Connected"
                    : "Unavailable"}
              </Badge>
            </div>
            <div>
              <span>Ollama</span>
              <Badge good={models.data?.available ?? false}>
                {models.loading
                  ? "Checking"
                  : models.data?.available
                    ? "Connected"
                    : "Unavailable"}
              </Badge>
            </div>
            <div>
              <span>Inference provider</span>
              <strong>Local · Ollama</strong>
            </div>
            <div>
              <span>Cloud API cost</span>
              <strong>No paid API required</strong>
            </div>
          </div>
          {health.error && (
            <ErrorState message={health.error} retry={health.refresh} />
          )}
        </section>
        <section className="panel">
          <PanelTitle
            title="Installed models"
            description="Models available from the configured Ollama service."
          />
          {models.loading ? (
            <Loading />
          ) : models.error ? (
            <ErrorState message={models.error} retry={models.refresh} />
          ) : (
            <div className="form-body">
              {models.data?.models.length ? (
                models.data.models.map((m) => (
                  <div className="model-row" key={m.name}>
                    <strong>{m.name}</strong>
                    <span>{(m.size / 1e9).toFixed(2)} GB</span>
                  </div>
                ))
              ) : (
                <p className="muted-text">
                  No models available. Pull a model using the command below.
                </p>
              )}
            </div>
          )}
        </section>
      </div>
      <section className="panel instructions">
        <PanelTitle
          title="Run your first local model"
          description="Run these commands from the AURA project directory."
        />
        <div className="form-body">
          <h3>1. Start the platform</h3>
          <pre>cp .env.example .env{"\n"}docker compose up --build -d</pre>
          <p>
            Edit your local .env password before starting. Docker stores your
            models and database in persistent volumes.
          </p>
          <h3>2. Download a small model</h3>
          <pre>docker compose exec ollama ollama pull llama3.2:1b</pre>
          <p>
            This is an explicit model download. Size, speed, and answer quality
            depend on the model and your hardware. The Docker service uses CPU
            inference on macOS.
          </p>
          <h3>3. Check connections, then open the playground</h3>
          <p>
            AURA discovers installed models automatically. No model is bundled
            or downloaded without an explicit command.
          </p>
        </div>
      </section>
      <div className="learning-note">
        <h3>Development workspace</h3>
        <p>
          This workspace is intended for local development. Authentication,
          deployment hardening, and external telemetry configuration are future
          work. Request content is stored in your local database so you can
          inspect and reproduce results.
        </p>
      </div>
    </>
  );
}
