FROM mcr.microsoft.com/playwright/python:v1.56.0-noble

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    ORDER_WORKER_RUNTIME_DIR=/tmp/order-worker \
    ORDER_WORKER_HEADLESS=1

COPY pyproject.toml ./
COPY order_worker ./order_worker
COPY scripts/railway-entrypoint.sh ./scripts/railway-entrypoint.sh

RUN python -m pip install --upgrade pip \
    && python -m pip install . \
    && apt-get update \
    && apt-get install -y --no-install-recommends fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/* \
    && chmod +x ./scripts/railway-entrypoint.sh

ENTRYPOINT ["./scripts/railway-entrypoint.sh"]
CMD ["sites"]
