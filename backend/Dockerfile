FROM python:3.11-slim AS builder

ARG INSTALL_THEME_ML=false

WORKDIR /build

RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH

COPY backend/requirements-runtime.txt backend/requirements-theme-ml.txt ./
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r requirements-runtime.txt && \
    if [ "$INSTALL_THEME_ML" = "true" ]; then pip install --no-cache-dir -r requirements-theme-ml.txt; fi

COPY backend/ /build/backend

FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    libpq5 \
    curl \
    fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd -r -g 1000 stockscanner && \
    useradd -r -u 1000 -g stockscanner stockscanner

ENV HOME=/app/data
ENV XDG_CACHE_HOME=/app/data/.cache
ENV PATH=/opt/venv/bin:$PATH
# Playwright browsers live outside the user's home so root can install them once
# and the non-root runtime user can read them.
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers

COPY --from=builder /opt/venv /opt/venv

# Install Chromium + its OS dependencies for TPEX (上櫃) chip fetching.
RUN playwright install --with-deps chromium && \
    chmod -R a+rX /opt/pw-browsers

COPY --chown=stockscanner:stockscanner backend/ .

RUN mkdir -p /app/data/.cache && \
    chown -R stockscanner:stockscanner /app/data

USER stockscanner

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
