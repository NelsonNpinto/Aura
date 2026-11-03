# Contributing

## Branch and commit

```sh
git switch -c <short-topic>
```

Keep a change to one concern. Commit messages: imperative subject under ~72 characters, then a body explaining *why* and naming what you verified. Never commit `.env`, Terraform state, database dumps, model weights, build output, or the `._` AppleDouble files macOS leaves on external drives (`python3 scripts/clean-macos-metadata.py` removes those).

## Definition of done

1. Code follows [DEVELOPMENT.md](DEVELOPMENT.md) conventions.
2. Ruff check and format pass; Pytest passes; the frontend builds.
3. Schema changes have an Alembic migration with a working `downgrade`, and `scripts/check-migrations.py` passes.
4. Behavioral changes are smoke-checked against the live stack.
5. Affected documents are updated in the same change.
6. The pull request states exactly which commands you ran and their outcome.

## Review checklist

**Contracts.** Every new Pydantic field bounded. No `$ref` reachable in a user-supplied JSON Schema. No unbounded list input.

**Honesty of measurement.** This is the part reviewers should be strictest about.

- Deterministic rule results, model estimates and human labels stay three separate things in storage and in the UI.
- A failed, invalid or non-finite metric is stored unscored with its error. No fallback score, no silent default, no substitution of a deterministic score for a judge score.
- No code path creates a human-looking label. Human calibration tables accept only real entered labels.
- UI copy does not upgrade "passed the output rules" into "correct", "safe" or "brand-suitable".

**Safety of execution.** Tool allowlist unchanged unless that is the point of the change. The calculator still parses a restricted arithmetic AST and never executes Python. Tool budget still bounds the agent loop. Customer lookup still accepts only mock IDs.

**Data handling.** Secrets come from the environment, never source. Full prompt/response content stays local and out of telemetry spans by default. Reviewer names, prompts and responses are private data in any export or dump.

**Compatibility.** Embedding dimension stays 384 unless the migration and a reindex are part of the change. No applied migration is edited. No endpoint path renamed without updating `frontend/src/services/api.ts` and [API_REFERENCE.md](API_REFERENCE.md).

## Documentation rules

- [VALIDATION.md](VALIDATION.md) records what was actually executed, with its date and its limits. Add a claim only after running the thing.
- [ROADMAP.md](ROADMAP.md) separates implemented stages from explicit extensions. Do not move an item up until it works.
- Keep README, USER_GUIDE and API_REFERENCE consistent with the code in the same change; a stale endpoint table is a defect.

## Reporting a problem

Include: what you ran, the full command, the observed output, `docker compose ps` state, and the relevant log tail (`docker compose logs --tail=100 backend`). For API issues, include the `X-Request-ID` from the response — it appears in the backend log line for that request. Common causes are listed under "Common issues" in [DEPLOYMENT.md](DEPLOYMENT.md).
