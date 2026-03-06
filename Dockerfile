# Google Calendar MCP Server
FROM python:3.11-slim-bookworm AS builder

WORKDIR /build
COPY requirements.txt pyproject.toml ./
COPY google_calendar_mcp/ google_calendar_mcp/

RUN pip install --no-cache-dir --upgrade pip && \
    pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.txt && \
    pip wheel --no-cache-dir --wheel-dir /wheels .

FROM python:3.11-slim-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

RUN useradd -m -u 1000 -s /bin/bash appuser

ENV HOME=/home/appuser \
    PATH=/home/appuser/.local/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PORT=7860

WORKDIR /app

COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir /wheels/*.whl && rm -rf /wheels

RUN chown -R appuser:appuser /app
USER appuser

EXPOSE 7860

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request, os; port=int(os.environ.get('PORT','7860')); urllib.request.urlopen(f'http://127.0.0.1:{port}/google-calendar/mcp')" || exit 1

CMD ["python", "-u", "-m", "google_calendar_mcp"]
