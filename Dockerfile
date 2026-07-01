FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN apt-get update \
 && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY backend ./backend
COPY css ./css
COPY js ./js
COPY index.html ./index.html

RUN mkdir -p /data
ENV SCANFOR_DB_PATH=/data/scanfor_red.db \
    SCANFOR_PROM_FILE_PATH=/prom \
    SCANFOR_PROM_POLL_SECONDS=60 \
    SCANFOR_ENABLE_PROM_WATCHER=false

EXPOSE 9000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD curl -fsS http://127.0.0.1:9000/api/health || exit 1

CMD ["python", "-m", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "9000"]
