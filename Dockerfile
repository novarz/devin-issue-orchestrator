FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install dependencies first for better layer caching.
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Copy only the orchestrator package (never the Superset source tree).
COPY devin_orchestrator /app/devin_orchestrator

EXPOSE 8000

# Run as a non-root user.
RUN useradd --create-home --uid 10001 orchestrator
USER orchestrator

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request, sys; \
    sys.exit(0) if urllib.request.urlopen('http://localhost:8000/healthz').status == 200 else sys.exit(1)"

CMD ["uvicorn", "devin_orchestrator.app:app", "--host", "0.0.0.0", "--port", "8000"]
