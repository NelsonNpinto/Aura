import { Link } from "react-router-dom";
import {
  Activity,
  ArrowRight,
  ArrowUpRight,
  CheckCheck,
  CircleCheck,
  Clock3,
  Cpu,
  FlaskConical,
  Plus,
  Terminal,
  TriangleAlert,
  Zap,
} from "lucide-react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
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
import { useModels } from "../contexts/ModelsContext";
import { date, number } from "../lib/utils";
import type { Evaluation, Overview as OverviewData, Trace } from "../types";
export function Overview() {
  const stats = useApi<OverviewData>("/overview"),
    runs = useApi<Evaluation[]>("/evaluations"),
    traces = useApi<Trace[]>("/traces"),
    models = useModels();
  const d = stats.data;
  return (
    <>
      <PageHeading
        eyebrow="YOUR RELIABILITY WORKSPACE"
        title="Overview"
        description="A clear view of how your AI applications are performing."
        action={
          <Button asChild>
            <Link to="/evaluations">
              <Plus size={16} />
              New evaluation
            </Link>
          </Button>
        }
      />
      <div className="environment-strip">
        <div>
          <span className="status-dot" />
          <strong>Local development</strong>
          <span className="strip-divider" />
          <span>Private, open-source, and powered by your models.</span>
        </div>
        <Link to="/settings">
          Environment details
          <ArrowUpRight size={14} />
        </Link>
      </div>
      {stats.error && (
        <ErrorState message={stats.error} retry={stats.refresh} />
      )}
      {stats.loading && !d ? (
        <Loading />
      ) : (
        <div className="metric-grid">
          {[
            {
              label: "AI requests",
              value: number(d?.total_requests),
              note: "Requests recorded in this workspace",
              icon: Zap,
            },
            {
              label: "Evaluation runs",
              value: number(d?.evaluation_runs),
              note: "Standalone & dataset evaluations",
              icon: FlaskConical,
            },
            {
              label: "Average check score",
              value:
                d?.average_check_score == null
                  ? "—"
                  : `${number(d.average_check_score * 100, 1)}%`,
              note: "Rule compliance · not factual quality",
              icon: CheckCheck,
            },
            {
              label: "Average latency",
              value:
                d?.average_latency_ms == null
                  ? "—"
                  : `${number(d.average_latency_ms / 1000, 2)}s`,
              note: "End-to-end model request time",
              icon: Clock3,
            },
          ].map((m) => (
            <article className="metric-card" key={m.label}>
              <div>
                <span>{m.label}</span>
                <m.icon size={17} />
              </div>
              <strong>{m.value}</strong>
              <p>{m.note}</p>
            </article>
          ))}
        </div>
      )}
      <div className="overview-columns">
        <section className="panel runs-panel">
          <PanelTitle
            title="Recent evaluations"
            description="Your latest output checks, all in one place."
            action={
              <Link className="text-link" to="/evaluations">
                View all
                <ArrowUpRight size={14} />
              </Link>
            }
          />
          {runs.error ? (
            <ErrorState message={runs.error} retry={runs.refresh} />
          ) : runs.loading ? (
            <Loading />
          ) : runs.data?.length ? (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Evaluation</th>
                    <th>Result</th>
                    <th>Score</th>
                    <th>Created</th>
                  </tr>
                </thead>
                <tbody>
                  {runs.data.slice(0, 5).map((r) => (
                    <tr key={r.id}>
                      <td>
                        <Link to="/evaluations">{r.name}</Link>
                        <small>{r.id.slice(0, 8)}</small>
                      </td>
                      <td>
                        <Badge good={r.passed}>
                          {r.passed ? "Passed" : "Failed"}
                        </Badge>
                      </td>
                      <td>{number(r.score * 100)}%</td>
                      <td className="muted-text">{date(r.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <Empty
              title="Great AI starts with a first evaluation"
              action={
                <Button variant="outline" asChild>
                  <Link to="/evaluations">
                    <Plus size={15} />
                    Create an evaluation
                  </Link>
                </Button>
              }
            >
              Test a response against clear rules.
              <br />
              Your results will appear here.
            </Empty>
          )}
          <div className="panel-foot">
            <CircleCheck size={14} />
            Real runs. Reproducible checks. No sample metrics.
          </div>
        </section>
        <section className="panel setup-panel">
          <PanelTitle
            title="Make your first run"
            description="A few small steps toward reliable AI."
          />
          <div className="setup-steps">
            {[
              {
                num: "01",
                title: "Connect a local model",
                text: models.data?.models.length
                  ? `${models.data.models.length} model(s) available`
                  : "Start Ollama and pull your first model.",
                path: "/settings",
                icon: Cpu,
                done: !!models.data?.models.length,
              },
              {
                num: "02",
                title: "Try the playground",
                text: "Write a prompt and inspect the response.",
                path: "/playground",
                icon: Terminal,
                done: !!d?.total_requests,
              },
              {
                num: "03",
                title: "Put the output to the test",
                text: "Define rules. Run checks. Find failures.",
                path: "/evaluations",
                icon: FlaskConical,
                done: !!d?.evaluation_runs,
              },
            ].map((s) => (
              <Link className="setup-step" to={s.path} key={s.num}>
                <span className={`step-number ${s.done ? "done" : ""}`}>
                  {s.done ? <CircleCheck size={17} /> : s.num}
                </span>
                <div>
                  <h3>{s.title}</h3>
                  <p>{s.text}</p>
                </div>
                <ArrowRight size={15} />
              </Link>
            ))}
          </div>
          <div className="setup-note">
            <ShieldIcon />
            No paid API keys needed.
            <br />
            Run inference on your own machine.
          </div>
        </section>
      </div>
      <div className="overview-columns bottom-columns">
        <section className="panel">
          <PanelTitle
            title="Model performance"
            description="Compare latency across successful requests."
            action={<span className="subtle-tag">LATENCY</span>}
          />
          {d?.model_comparison.length ? (
            <div className="chart">
              <ResponsiveContainer width="100%" height={220}>
                <BarChart data={d.model_comparison}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="model" tick={{ fontSize: 11 }} />
                  <YAxis unit="ms" tick={{ fontSize: 11 }} />
                  <Tooltip />
                  <Bar
                    dataKey="latency_ms"
                    name="Average latency (ms)"
                    fill="#6466c8"
                    radius={[5, 5, 0, 0]}
                  />
                </BarChart>
              </ResponsiveContainer>
            </div>
          ) : (
            <div className="quiet-empty">
              <Activity size={26} />
              <h3>No model activity yet</h3>
              <p>Run a prompt to start measuring performance.</p>
              <Link to="/playground" className="text-link">
                Open playground
                <ArrowRight size={14} />
              </Link>
            </div>
          )}
        </section>
        <section className="panel">
          <PanelTitle
            title="Reliability signals"
            description="Only measured signals belong here."
          />
          <div className="signal-list">
            <div>
              <span>
                <TriangleAlert size={16} />
                Request errors
              </span>
              <strong>{number(d?.request_errors)}</strong>
            </div>
            <div>
              <span>
                <FlaskConical size={16} />
                Failed evaluations
              </span>
              <strong>{number(d?.failed_evaluations)}</strong>
            </div>
            <div>
              <span>
                <Cpu size={16} />
                Recorded tokens
              </span>
              <strong>
                {d?.input_tokens == null && d?.output_tokens == null
                  ? "—"
                  : number((d?.input_tokens ?? 0) + (d?.output_tokens ?? 0))}
              </strong>
            </div>
            <div>
              <span>Faithfulness / relevance</span>
              {d?.faithfulness == null ? (
                <Badge>Not measured</Badge>
              ) : (
                <strong>
                  {number(d.faithfulness * 100)}% /{" "}
                  {number((d.answer_relevance ?? 0) * 100)}%
                </strong>
              )}
            </div>
          </div>
          <div className="signal-note">
            Judge scores are model estimates. Review their calibration before
            using them as quality gates.
          </div>
        </section>
      </div>
      <div className="metric-grid">
        {[
          {
            label: "Faithfulness · judge estimate",
            value:
              d?.faithfulness == null
                ? "—"
                : `${number(d.faithfulness * 100)}%`,
          },
          {
            label: "Relevance · judge estimate",
            value:
              d?.answer_relevance == null
                ? "—"
                : `${number(d.answer_relevance * 100)}%`,
          },
          {
            label: "Reviews flagging unsupported claims",
            value: d?.judge_reviews ? number(d.unsupported_claim_reviews) : "—",
          },
          {
            label: "Local provider inference fees",
            value:
              d?.estimated_cost == null
                ? "—"
                : `$${number(d.estimated_cost, 2)}`,
          },
        ].map((m) => (
          <div className="metric-card" key={m.label}>
            <div>{m.label}</div>
            <strong>{m.value}</strong>
            <p>Based on stored results · no sample metrics</p>
          </div>
        ))}
      </div>
      {!!traces.data?.some((t) => t.status === "error") && (
        <section className="panel failure-panel">
          <PanelTitle
            title="Recent request failures"
            action={
              <Link to="/traces" className="text-link">
                Inspect traces
                <ArrowUpRight size={14} />
              </Link>
            }
          />
          {traces.data
            .filter((t) => t.status === "error")
            .slice(0, 3)
            .map((t) => (
              <div className="failure-row" key={t.id}>
                <TriangleAlert size={17} />
                <strong>{t.model}</strong>
                <span>{t.error}</span>
                <small>{date(t.created_at)}</small>
              </div>
            ))}
        </section>
      )}
    </>
  );
}
function ShieldIcon() {
  return <CheckCheck size={17} />;
}
