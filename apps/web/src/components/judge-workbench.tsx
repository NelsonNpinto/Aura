"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import {
  Badge,
  Button,
  Card,
  ErrorNote,
  Input,
  Label,
  Metric,
  Textarea,
} from "@/components/ui";

type Judgment = {
  id: string;
  metrics: { passed: boolean | null; score: number | null };
  results: {
    input: { question: string; answer: string; context: string };
    verdict: Record<string, unknown> | null;
    error: string | null;
  }[];
};

function HumanReview({
  judgment,
  onSaved,
}: {
  judgment: Judgment;
  onSaved: () => void;
}) {
  const [comment, setComment] = useState("");
  const [score, setScore] = useState(80);
  const mutation = useMutation({
    mutationFn: (passed: boolean) =>
      api(`/quality/judgments/${judgment.id}/label`, {
        method: "POST",
        body: JSON.stringify({ passed, score, comment }),
      }),
    onSuccess: onSaved,
  });
  return (
    <div className="space-y-2 rounded border border-border p-3">
      <div className="flex gap-2">
        <strong>{judgment.results[0]?.input.question}</strong>
        <Badge
          tone={
            judgment.metrics.passed === null
              ? "warn"
              : judgment.metrics.passed
                ? "ok"
                : "danger"
          }
        >
          {judgment.metrics.passed === null
            ? "unscored"
            : judgment.metrics.passed
              ? "judge pass"
              : "judge fail"}
        </Badge>
      </div>
      <p className="whitespace-pre-wrap text-sm">
        {judgment.results[0]?.input.answer}
      </p>
      <details>
        <summary>Judge evidence</summary>
        <pre className="overflow-auto whitespace-pre-wrap text-xs">
          {JSON.stringify(
            judgment.results[0]?.verdict ?? {
              error: judgment.results[0]?.error,
            },
            null,
            2,
          )}
        </pre>
      </details>
      <Label>
        Your review comment
        <Input value={comment} onChange={(e) => setComment(e.target.value)} />
      </Label>
      <Label>
        Your score (0–100)
        <Input
          type="number"
          min={0}
          max={100}
          value={score}
          onChange={(e) => setScore(Number(e.target.value))}
        />
      </Label>
      <div className="flex gap-2">
        <Button
          disabled={!comment || mutation.isPending}
          onClick={() => mutation.mutate(true)}
        >
          Human: pass
        </Button>
        <Button
          variant="secondary"
          disabled={!comment || mutation.isPending}
          onClick={() => mutation.mutate(false)}
        >
          Human: fail
        </Button>
      </div>
      <ErrorNote error={mutation.error} />
      {mutation.isSuccess && (
        <p className="text-sm text-ok">Your review was saved.</p>
      )}
    </div>
  );
}

export function JudgeWorkbench() {
  const qc = useQueryClient();
  const [question, setQuestion] = useState(
    "Does this marketing draft follow the supplied product facts?",
  );
  const [context, setContext] = useState(
    "Synthetic product: battery lasts up to 8 hours. Maximum permitted discount: 10%.",
  );
  const [answer, setAnswer] = useState(
    "Enjoy 48-hour battery life and a 30% discount.",
  );
  const reviews = useQuery({
    queryKey: ["judgments"],
    queryFn: () =>
      api<{
        judgments: Judgment[];
        calibration: {
          sample_size: number;
          agreement: number | null;
          kappa: number | null;
          false_passes: string[];
          false_fails: string[];
        };
        limits: string;
      }>("/quality/judgments"),
    retry: false,
  });
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ["judgments"] });
  };
  const judge = useMutation({
    mutationFn: () =>
      api("/quality/judge", {
        method: "POST",
        body: JSON.stringify({ question, context, answer }),
      }),
    onSuccess: refresh,
  });
  const draft = useMutation({
    mutationFn: () => api<{draft:string}>("/quality/marketing-draft", {
      method:"POST", body:JSON.stringify({facts:context}),
    }),
    onSuccess: (data) => setAnswer(data.draft),
  });
  return (
    <Card className="space-y-4">
      <h2 className="text-lg font-semibold">Judge and human calibration</h2>
      <p className="text-sm text-muted">
        The prefilled marketing example is synthetic. Run the model judge,
        inspect its reasoning, then record your own assessment. Human labels are
        never generated automatically.
      </p>
      <Label>
        Question
        <Input
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          maxLength={2000}
        />
      </Label>
      <Label>
        Supporting facts or policy
        <Textarea
          value={context}
          onChange={(e) => setContext(e.target.value)}
          maxLength={12000}
        />
      </Label>
      <Label>
        AI output to evaluate
        <Textarea
          value={answer}
          onChange={(e) => setAnswer(e.target.value)}
          maxLength={8000}
        />
      </Label>
      <Button
        disabled={judge.isPending || !question || !answer}
        onClick={() => judge.mutate()}
      >
        {judge.isPending ? "Evaluating…" : "Run model judge"}
      </Button>
      <Button variant="secondary" disabled={draft.isPending || !context} onClick={()=>draft.mutate()}>
        {draft.isPending ? "Drafting…" : "Generate a draft from these facts"}
      </Button>
      <ErrorNote error={draft.error ?? judge.error ?? reviews.error} />
      {reviews.data && (
        <>
          <div className="grid gap-4 sm:grid-cols-3">
            <Metric
              label="Human-labelled comparisons"
              value={reviews.data.calibration.sample_size}
              source="Actual reviewer submissions"
            />
            <Metric
              label="Observed agreement"
              value={
                reviews.data.calibration.agreement === null
                  ? null
                  : `${(reviews.data.calibration.agreement * 100).toFixed(1)}%`
              }
              source="Majority human verdict versus model"
            />
            <Metric
              label="Cohen's kappa"
              value={
                reviews.data.calibration.kappa === null
                  ? "undefined / insufficient labels"
                  : reviews.data.calibration.kappa.toFixed(3)
              }
              source="Paired verdicts"
            />
          </div>
          <p className="text-xs text-muted">
            {reviews.data.limits} False passes:{" "}
            {reviews.data.calibration.false_passes.length}; false fails:{" "}
            {reviews.data.calibration.false_fails.length}. Small samples do not
            establish reliability.
          </p>
          {reviews.data.judgments.map((j) => (
            <HumanReview key={j.id} judgment={j} onSaved={refresh} />
          ))}
        </>
      )}
    </Card>
  );
}
