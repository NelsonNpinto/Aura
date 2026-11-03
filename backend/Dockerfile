FROM python:3.12-slim
WORKDIR /app
RUN groupadd --gid 10001 aura && useradd --uid 10001 --gid aura --create-home aura
RUN mkdir /models && chown aura:aura /models
COPY --from=ghcr.io/astral-sh/uv:0.13.6 /uv /uvx /bin/
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --extra rag
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./
ENV HF_HOME=/models RAGAS_DO_NOT_TRACK=true
RUN chown -R aura:aura /app/app /app/alembic /app/alembic.ini /app/pyproject.toml /app/uv.lock
USER aura
EXPOSE 8000
CMD ["sh", "-c", "uv run --no-sync alembic upgrade head && uv run --no-sync uvicorn app.main:app --host 0.0.0.0 --port 8000"]
