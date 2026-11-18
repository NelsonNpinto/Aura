# Mock ERP container (Phase 5.4): REST + stateless Streamable HTTP MCP server.
FROM python:3.12-slim-bookworm
RUN useradd --create-home --uid 10002 erp
WORKDIR /app
COPY services/erp-mock/ ./
RUN pip install --no-cache-dir . "uvicorn[standard]>=0.38"
USER erp
EXPOSE 8001
CMD ["uvicorn", "erp_mock.app:app", "--host", "0.0.0.0", "--port", "8001"]
