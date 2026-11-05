# ADR-003: Auth and tenancy

- **Status:** accepted
- **Date:** 2026-11-04

## Decision

- **Identity:** Better Auth in `apps/web`, tables in Postgres schema `auth` (`schemaName: "auth"`). Email/password, optional GitHub, organization plugin (roles guest/clerk/approver/controller/auditor/admin), anonymous plugin for guests, JWT plugin (EdDSA) and Turnstile through the captcha plugin.
- **API:** FastAPI verifies the JWT against `/api/auth/jwks` (issuer = site URL, audience `aura-api`, 15-minute expiry). Claims: `sub`, `org_id`, `roles`, `guest`. Scripts use argon2-hashed API keys (`aura_<prefix>_<secret>`), shown once.
- **Guests** join the shared `demo` org with role `guest`; registered users get a personal org as `admin`. Org resolution falls back to the first membership because Better Auth can create the session before the sign-up hook inserts it.
- **RLS:** every tenant table has `org_id` and a policy `org_id = current_setting('app.org_id', true)` for role `aura_app`. Each tenant transaction runs `SET LOCAL ROLE aura_app` and `set_config('app.org_id', …, true)`. Both are transaction-scoped, so Neon's pooler can't leak a tenant across requests. System jobs (migrations, seed, API-key lookup) run as the owner role.
- Prompt versions are immutable twice over: `aura_app` has no UPDATE/DELETE on `ai.prompts`, and a trigger rejects them for every role.

## Consequences

- Tests prove: 40 concurrent transactions over one pool never see another org's rows; `WITH CHECK` blocks cross-org writes; no tenant set → no rows; the setting doesn't survive into the next transaction on the same connection.
