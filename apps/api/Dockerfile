# AURA API container (Phase 5.4). Used by the Helm chart and the kind e2e test, not by Vercel.
# Multi-stage so the runtime image carries no build tools; no torch anywhere (§B4).
FROM ghcr.io/astral-sh/uv:0.13.8-python3.12-bookworm-slim AS build
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY apps/api/pyproject.toml apps/api/uv.lock ./
COPY services/erp-mock /services/erp-mock
RUN uv sync --frozen --no-dev --no-install-project
COPY apps/api/ ./
RUN uv sync --frozen --no-dev

FROM python:3.12-slim-bookworm AS runtime
RUN useradd --create-home --uid 10001 aura
WORKDIR /app
COPY --from=build --chown=aura:aura /app /app
COPY --from=build --chown=aura:aura /services/erp-mock /services/erp-mock
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 APP_ENV=production
USER aura
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/api/v1/health').status==200 else 1)"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
