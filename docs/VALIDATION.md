# Validation — 3 November 2026

## Passed locally

- 24 Pytest cases: output rules (including rejection of non-JSON NaN/Infinity), invalid check configurations, saved evaluations and aggregates, successful/failed generation trace handling through a stubbed provider, missing usage values, offline discovery, source-response linkage, and request validation.
- Ruff checks and formatting.
- TypeScript compilation and Vite production build.
- npm dependency audit during installation: no reported vulnerabilities.
- Docker Compose configuration validation (no daemon needed).
- Alembic offline PostgreSQL SQL generation: vector extension, tables, foreign key, and indexes.
- Browser workflow against an isolated SQLite test database: a non-empty/required-keywords evaluation passed at 100%; removing a required phrase failed at 50% with a missing-phrase explanation; history and dashboard updated to two runs, one failure, 75% average check score.
- Responsive dashboard rendering, mobile navigation, and Settings service status. Preview data is explicitly marked as test data. No generated/model response was fabricated for these checks.

## Blocked / not verified locally

Docker Desktop initially responded and had another project's services running. During AURA's Ollama image pull, Docker stopped; its log reported `no space left on device`. The internal drive had approximately 2.4 GiB available when inspected. No unrelated images, volumes, or containers were deleted, and Docker was not reset.

Consequently, a full Compose build/start, live PostgreSQL migration round trip, pgvector extension loading, and real Ollama generation have not been verified locally. CI includes jobs for builds and a real PostgreSQL/pgvector migration round trip; no GitHub execution is claimed.

## Preview

The running browser preview uses Vite on `127.0.0.1:5273` and a temporary API process on `127.0.0.1:8200`, with an isolated SQLite database under `/tmp`. The production entry point has no automatic SQLite fallback and Compose configures PostgreSQL. The test preview is temporary and does not prove database-container or model readiness.

After disk space is available and Docker Desktop is running again, use the configured `.env` and run:

```sh
docker compose up --build -d
docker compose ps
docker compose exec ollama ollama pull llama3.2:1b
```

Stop the temporary frontend/API preview processes before Compose binds the same ports. Then verify Settings, generate a real prompt, evaluate its response, and inspect its saved trace.
