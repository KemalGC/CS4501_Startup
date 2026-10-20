FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PROOFGRADE_HINT_MODE=demo \
    PROOFGRADE_STORE_ATTEMPTS=false \
    PROOFGRADE_DB_PATH=/data/proofgrade.sqlite3 \
    PROOFGRADE_TEACHER_DB=/data/teachers.sqlite3

WORKDIR /app
COPY requirements.lock pyproject.toml README.md ./
COPY proofgrade ./proofgrade
RUN python -m pip install --no-cache-dir -r requirements.lock \
    && python -m pip install --no-cache-dir --no-deps . \
    && useradd --create-home --uid 10001 app \
    && mkdir -p /data && chown app:app /data

USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"
CMD ["python", "-m", "uvicorn", "proofgrade.api:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
