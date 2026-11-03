import { RefreshCw } from "lucide-react";
import { Link } from "react-router-dom";
import {
  Badge,
  ErrorState,
  Loading,
  PageHeading,
  PanelTitle,
} from "../components/common";
import { Inspect, Note } from "../components/platform";
import { Button } from "../components/ui/button";
import { useApi } from "../hooks/useApi";
import { number } from "../lib/utils";
import type { Monitoring as MonitoringData } from "../types/platform";
export function Monitoring() {
  const query = useApi<MonitoringData>("/monitoring"),
    d = query.data;
  return (
    <>
      <PageHeading
        eyebrow="HEALTH & OPERATIONS"
        title="Monitoring"
        description="Operational signals from stored requests, evaluations, and tools."
        action={
          <Button variant="outline" onClick={() => void query.refresh()}>
            <RefreshCw size={15} />
            Refresh
          </Button>
        }
      />
      {query.error ? (
        <ErrorState message={query.error} retry={query.refresh} />
      ) : query.loading ? (
        <Loading />
      ) : (
        d && (
          <>
            <div className="metric-grid">
              {[
                {
                  label: "Recorded requests in window",
                  value: number(d.window_requests),
                },
                {
                  label: "Request error rate",
                  value:
                    d.error_rate == null
                      ? "—"
                      : `${number(d.error_rate * 100, 1)}%`,
                },
                {
                  label: "P95 latency",
                  value:
                    d.p95_latency_ms == null
                      ? "—"
                      : `${number(d.p95_latency_ms)} ms`,
                },
                {
                  label: "Provider inference fees",
                  value:
                    d.cloud_inference_cost_usd == null
                      ? "—"
                      : `$${number(d.cloud_inference_cost_usd, 2)}`,
                },
              ].map((m) => (
                <div className="metric-card" key={m.label}>
                  <div>{m.label}</div>
                  <strong>{m.value}</strong>
                  <p>
                    Latest {d.window_limit.toLocaleString()} requests maximum
                  </p>
                </div>
              ))}
            </div>
            <div className="platform-grid">
              <section className="panel">
                <PanelTitle title="Observability integrations" />
                <div className="signal-list">
                  <div>
                    <span>OpenTelemetry export</span>
                    <Badge good={d.otel_configured}>
                      {d.otel_configured ? "Configured" : "Not configured"}
                    </Badge>
                  </div>
                  <div>
                    <span>Langfuse export</span>
                    <Badge good={d.langfuse_configured}>
                      {d.langfuse_configured ? "Configured" : "Not configured"}
                    </Badge>
                  </div>
                  <div>
                    <span>API authentication</span>
                    <Badge good={d.api_auth_enabled}>
                      {d.api_auth_enabled ? "Enabled" : "Local workspace"}
                    </Badge>
                  </div>
                  <div>
                    <span>Failure webhook</span>
                    <Badge good={d.webhook_enabled}>
                      {d.webhook_enabled ? "Enabled" : "Secret required"}
                    </Badge>
                  </div>
                  <div>
                    <span>Recorded tokens · in / out</span>
                    <strong>
                      {number(d.input_tokens)} / {number(d.output_tokens)}
                    </strong>
                  </div>
                </div>
                <div className="signal-note">
                  Configured means credentials or endpoint are present. It does
                  not confirm delivery to the external collector.
                </div>
              </section>
              <section className="panel">
                <PanelTitle title="Stored workspace activity" />
                <div className="signal-list">
                  {Object.entries(d.counts).map(([k, v]) => (
                    <div key={k}>
                      <span>{k.replaceAll("_", " ")}</span>
                      <strong>{number(v)}</strong>
                    </div>
                  ))}
                </div>
              </section>
            </div>
            <Note title="Local traces are always inspectable">
              Request content, generation configuration, usage, latency, and
              errors are stored locally. OpenTelemetry and optional self-hosted
              Langfuse receive operation spans when configured. Full prompt
              content is not exported by default. {d.cost_note}
            </Note>
            <section className="panel section-gap">
              <PanelTitle title="Operations" />
              <div className="form-body">
                <Inspect label="Operation counts" value={d.operations} />
              </div>
            </section>
            <section className="panel section-gap">
              <PanelTitle
                title="Recent request errors"
                action={
                  <Link to="/traces" className="text-link">
                    Inspect request traces
                  </Link>
                }
              />
              <div className="record-list">
                {d.recent_errors.length ? (
                  d.recent_errors.map((e) => (
                    <div key={e.id} className="record-item">
                      <h3>
                        {e.model} · {e.id.slice(0, 8)}
                      </h3>
                      <p className="inline-error">{e.error}</p>
                    </div>
                  ))
                ) : (
                  <p className="muted-text">No request errors recorded.</p>
                )}
              </div>
            </section>
          </>
        )
      )}
    </>
  );
}
