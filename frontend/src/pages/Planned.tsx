import { Link, useLocation } from "react-router-dom";
import { ArrowRight, Construction } from "lucide-react";
import { Button } from "../components/ui/button";
import { PageHeading } from "../components/common";
const modules: Record<string, [string, string]> = {
  "/knowledge-base": [
    "Knowledge Base",
    "Document extraction, local embeddings, pgvector search, BM25, and cited RAG responses.",
  ],
  "/ai-judge": [
    "AI Judge",
    "Structured rubric-based scoring with validated local model judgments.",
  ],
  "/judge-reliability": [
    "Judge Reliability",
    "Human labels, agreement, Cohen’s kappa, and false-pass analysis.",
  ],
  "/experiments": [
    "Experiments",
    "Reproducible model, prompt, and retrieval comparisons.",
  ],
  "/agents": ["Agents", "LangGraph tool execution and agent trace evaluation."],
  "/regression-tests": [
    "Regression Tests",
    "Datasets, baselines, and configurable release quality gates.",
  ],
  "/monitoring": [
    "Monitoring",
    "OpenTelemetry and Langfuse instrumentation and signal monitoring.",
  ],
  "/failure-inbox": [
    "Failure Inbox",
    "Authenticated, deduplicated failure ingestion and approval into regression cases.",
  ],
  "/security": [
    "Security",
    "Prompt injection test datasets and promptfoo integration.",
  ],
  "/marketing": [
    "Marketing Evaluation",
    "Brand and product policy checks with human approval.",
  ],
};
export function Planned() {
  const path = useLocation().pathname;
  const entry = modules[path];
  return (
    <>
      <PageHeading
        eyebrow="PROJECT ROADMAP"
        title={entry?.[0] ?? "Page not found"}
        description={entry?.[1] ?? "This route does not exist."}
      />
      <div className="planned-panel">
        <Construction size={30} />
        <span className="subtle-tag">{entry ? "PLANNED MODULE" : "404"}</span>
        <h2>{entry ? "Built step by step" : "Let’s get you back to work"}</h2>
        <p>
          {entry
            ? "This module is outlined in the AURA roadmap and has not been implemented yet. The first milestone delivers local inference, deterministic evaluation, and stored request traces."
            : "Head to the overview to find your workspace."}
        </p>
        <Button asChild>
          <Link to={entry ? "/evaluations" : "/"}>
            {entry ? "Try evaluations" : "Back to overview"}
            <ArrowRight size={15} />
          </Link>
        </Button>
      </div>
    </>
  );
}
