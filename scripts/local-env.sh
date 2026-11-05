#!/usr/bin/env bash
# Source before local dev/tests: points every service at the local Docker stack, even when
# .env.local holds production values (process env wins over .env files in both apps).
export APP_ENV=local
export DATABASE_URL=postgresql://aura:aura-local-only@localhost:5434/aura
export DATABASE_URL_UNPOOLED=$DATABASE_URL
export UPSTASH_REDIS_REST_URL=http://localhost:8079
export UPSTASH_REDIS_REST_TOKEN=local-upstash-token
export BETTER_AUTH_URL=http://localhost:3000
export WEB_ORIGIN=http://localhost:3000
export AURA_JWKS_URL=http://localhost:3000/api/auth/jwks
export AURA_JWT_ISSUER=http://localhost:3000
# Cloudflare's documented always-pass test keys
export TURNSTILE_SITE_KEY=1x00000000000000000000AA
export NEXT_PUBLIC_TURNSTILE_SITE_KEY=1x00000000000000000000AA
export TURNSTILE_SECRET_KEY=1x0000000000000000000000000000000AA
export LANGFUSE_PUBLIC_KEY= LANGFUSE_SECRET_KEY= BLOB_READ_WRITE_TOKEN=
export NEO4J_URI=bolt://localhost:7687 NEO4J_USERNAME=neo4j NEO4J_PASSWORD=aura-local-only NEO4J_DATABASE=neo4j
export AURA_API_DEV_ORIGIN=http://localhost:8010
export ERP_SERVICE_TOKEN=local-erp-service-token
export APPROVAL_TOKEN_SECRET=local-approval-token-secret
