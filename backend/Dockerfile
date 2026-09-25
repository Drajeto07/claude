# syntax=docker/dockerfile:1
#
# SmartDoc Formatter's backend (корекции.docx §67). One image, three commands:
#   the API (default):   uvicorn, as below
#   the job worker:      arq app.worker.WorkerSettings
#   migrations:          alembic upgrade head   (a release step, before the API starts)
#
#   docker build -t smartdoc-backend backend

FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Fonts for the PDF export (app/export/fonts.py searches /usr/share/fonts):
# Liberation matches Arial / Times New Roman / Courier New in size, DejaVu adds a
# wide character range; both cover Cyrillic.
RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-liberation fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# The runtime lock only (no test tools), every package checked against its hash.
COPY requirements.lock ./
RUN pip install --require-hashes -r requirements.lock

COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app
COPY scripts ./scripts

# Not root. /app/data holds local asset storage, when STORAGE_BACKEND=local.
RUN useradd --create-home --uid 10001 smartdoc \
    && mkdir -p /app/data \
    && chown smartdoc /app/data
USER smartdoc

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4)"]

# A production server, never `fastapi dev`. uvicorn takes its worker count from
# WEB_CONCURRENCY and trusts X-Forwarded-For only from FORWARDED_ALLOW_IPS (set it
# to the reverse proxy's address, so rate limits and audit lines see real
# clients). Its own access log is off: LOG_REQUESTS=true writes the app's
# structured line per request instead.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--no-access-log"]
