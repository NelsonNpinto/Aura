import { useState } from "react";
import { Badge, PageHeading, PanelTitle } from "../components/common";
import {
  ActionButton,
  Checks,
  DataPanel,
  MutationError,
  Note,
  splitList,
} from "../components/platform";
import { useApi } from "../hooks/useApi";
import { useMutation } from "../hooks/useMutation";
import { api } from "../services/api";
import { number } from "../lib/utils";
import type { MarketingReview } from "../types/platform";
export function Marketing() {
  const history = useApi<MarketingReview[]>("/marketing/reviews"),
    action = useMutation<MarketingReview>(),
    approval = useMutation<MarketingReview>();
  const [content, setContent] = useState(""),
    [brand, setBrand] = useState(""),
    [facts, setFacts] = useState(""),
    [forbidden, setForbidden] = useState(""),
    [audience, setAudience] = useState(""),
    [discounts, setDiscounts] = useState(""),
    [json, setJson] = useState(false),
    [reviewer, setReviewer] = useState(""),
    [feedback, setFeedback] = useState(""),
    [selected, setSelected] = useState(""),
    [decision, setDecision] = useState("rejected");
  const show = (r: MarketingReview) => (
    <>
      <div className="record-heading">
        <h3>Content review</h3>
        <Badge
          good={
            r.decision === "approved"
              ? true
              : r.decision === "rejected"
                ? false
                : undefined
          }
        >
          {r.decision}
        </Badge>
        <strong>{number(r.score * 100)}%</strong>
        <button className="text-link" onClick={() => setSelected(r.id)}>
          Human decision
        </button>
      </div>
      <pre>{r.content}</pre>
      <Checks results={r.results} />
      {r.reviewer && (
        <p className="muted-text">
          {r.reviewer}: {r.feedback}
        </p>
      )}
    </>
  );
  return (
    <>
      <PageHeading
        eyebrow="SPECIALIZED EVALUATION PACK"
        title="Marketing evaluation"
        description="Check brand and product rules, then route content for human approval."
      />
      <div className="platform-grid">
        <section className="panel">
          <PanelTitle title="Evaluate marketing content" />
          <form
            className="form-body"
            onSubmit={(e) => {
              e.preventDefault();
              void action.execute(
                async () =>
                  (
                    await api.post("/marketing/reviews", {
                      content,
                      brand_keywords: splitList(brand),
                      product_facts: splitList(facts),
                      forbidden_claims: splitList(forbidden),
                      audience_keywords: splitList(audience),
                      allowed_discounts: splitList(discounts),
                      require_json: json,
                    })
                  ).data,
                "Marketing review saved",
                history.refresh,
              );
            }}
          >
            <label>
              Generated content
              <textarea
                rows={6}
                value={content}
                onChange={(e) => setContent(e.target.value)}
              />
            </label>
            {[
              { label: "Required brand terms", value: brand, set: setBrand },
              { label: "Required product facts", value: facts, set: setFacts },
              {
                label: "Forbidden claims / policy phrases",
                value: forbidden,
                set: setForbidden,
              },
              {
                label: "Target audience terms",
                value: audience,
                set: setAudience,
              },
              {
                label: "Allowed percentage discounts",
                value: discounts,
                set: setDiscounts,
              },
            ].map((f) => (
              <label key={f.label}>
                {f.label} (one per line)
                <textarea
                  rows={2}
                  value={f.value}
                  onChange={(e) => f.set(e.target.value)}
                />
              </label>
            ))}
            <label className="inline-checkbox">
              <input
                type="checkbox"
                checked={json}
                onChange={(e) => setJson(e.target.checked)}
              />
              Require valid JSON output
            </label>
            <MutationError error={action.error} />
            <ActionButton busy={action.busy}>Run marketing checks</ActionButton>
          </form>
        </section>
        <div>
          {action.result && (
            <section className="panel">
              <PanelTitle title="Latest review" />
              <div className="form-body">{show(action.result)}</div>
            </section>
          )}
          <Note title="Explicit policies, human judgment">
            Brand, product, and audience checks match the terms you supply. They
            do not establish semantic brand fit or independently verify every
            product claim. All percentage mentions are conservatively checked
            against the discount allowlist. A person must review the copy before
            approval.
          </Note>
          {selected && (
            <section className="panel section-gap">
              <PanelTitle
                title="Human approval"
                description={selected.slice(0, 8)}
              />
              <form
                className="form-body"
                onSubmit={(e) => {
                  e.preventDefault();
                  void approval.execute(
                    async () =>
                      (
                        await api.put(
                          `/marketing/reviews/${selected}/decision`,
                          { reviewer, feedback, decision },
                        )
                      ).data,
                    "Decision recorded",
                    history.refresh,
                  );
                }}
              >
                <label>
                  Reviewer
                  <input
                    required
                    value={reviewer}
                    onChange={(e) => setReviewer(e.target.value)}
                  />
                </label>
                <label>
                  Decision
                  <select
                    value={decision}
                    onChange={(e) => setDecision(e.target.value)}
                  >
                    <option value="rejected">Reject</option>
                    <option value="approved">
                      Approve (all checks must pass)
                    </option>
                  </select>
                </label>
                <label>
                  Feedback
                  <textarea
                    rows={3}
                    value={feedback}
                    onChange={(e) => setFeedback(e.target.value)}
                  />
                </label>
                <MutationError error={approval.error} />
                <ActionButton busy={approval.busy}>
                  Record decision
                </ActionButton>
              </form>
            </section>
          )}
        </div>
      </div>
      <DataPanel
        title="Marketing review history"
        query={history}
        render={show}
      />
    </>
  );
}
