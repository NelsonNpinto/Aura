# Postmortems

Written for real incidents only. An entry here means something actually broke; nothing is
invented to fill the page. Blameless: the question is what the system let happen, not who typed
it.

## Template

```markdown
## YYYY-MM-DD — <one-line summary>

**Impact.** Who or what was affected, for how long, and how it was visible.
**Detection.** What told us, and how long after it started.
**Timeline.** UTC, with the evidence (run id, workflow run, commit).
**Cause.** The chain of conditions, not a single culprit.
**Fix.** What was changed, with the commit.
**Prevention.** The test, gate or runbook entry that would catch it next time, and whether it exists yet.
**Not fixed.** What is still open, honestly.
```

## 2026-11-05 — Production deploy failed at demo seeding

**Impact.** The first production deploy of the rebuild did not complete. The API migration step
failed, deploy and smoke were skipped, and the live URL kept serving the previous build. No data
was lost and no user-facing behaviour changed, because the deploy never reached production.

**Detection.** The `deploy.yml` run failed on its migration/seed step
([run 41995246447](https://github.com/NelsonNpinto/Aura/actions/runs/41995246447)). It was
noticed from the workflow result, not from an alert.

**Timeline (UTC).**
- Deploy started after a merge to `main`.
- API and web jobs passed; the migration/seed step raised
  `BLOB_READ_WRITE_TOKEN required outside local/test`.
- Deploy and smoke steps were skipped by the dependency on that step.

**Cause.** The demo seed uploaded the synthetic policy corpus through the blob store, so seeding
required blob credentials in CI. CI deliberately does not hold private-upload credentials. The
seed therefore could not run anywhere except a developer machine with a token, and the deploy
pipeline depended on it.

**Fix.** The immutable synthetic policies are bundled into the API package and seeded from disk;
only genuinely private uploads need the blob store. An authenticated source-file endpoint serves
the bundled documents. Fixture fallback labels were corrected at the same time so a simulated
response can never claim to be recorded live evidence.

**Prevention.** The migration round-trip and the seed now run in `ci.yml` on an ephemeral
Postgres without any blob credentials, so this class of failure is caught before `main`.

**Not fixed at the time.** The deploy pipeline still had no explicit check that production
secrets exist before migrations run; a missing secret surfaces as a step failure rather than a
clear precondition error.

## 2026-11-05 — Decimal values broke the router's response cache

**Impact.** A live extraction smoke test failed after a successful deploy. Extraction worked, but
caching the structured result raised a JSON serialisation error on `Decimal` quantities, so the
affected calls failed instead of being served from cache. Caught before the authorised rollout
continued.

**Detection.** The live extraction smoke run, not a unit test: the fixture path used strings and
never produced a `Decimal`.

**Cause.** Extraction normalises quantities to `Decimal` for exact arithmetic (money and
quantities must never be floats). The exact-match cache serialised the parsed object with the
default JSON encoder, which does not know `Decimal`.

**Fix.** The cache encoder handles `Decimal`, and a regression test caches a result containing a
decimal quantity.

**Prevention.** The regression test runs in the PR tier. The wider lesson — fixtures that are
"close enough" to live data hide type errors — is why the live smoke test exists at all.

**Not fixed.** Fixture data still uses strings where live extraction produces `Decimal`;
the fixtures match the schema, not the runtime types.
