FROM python:3.12-slim

LABEL org.opencontainers.image.title="xiaoheihe-cli"
LABEL description="小黑盒游戏记录与社区操作 CLI 和 REST 服务"

WORKDIR /app

# Shared, read-only browser binaries for the non-root application user.
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/playwright-browsers

# Install system dependencies for Chromium
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget gnupg ffmpeg \
    libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 libxkbcommon0 \
    libxcomposite1 libxdamage1 libxrandr2 libgbm1 libpango-1.0-0 \
    libcairo2 libasound2 libxshmfence1 libx11-xcb1 libx11-6 libxcb1 \
    libfontconfig1 libfreetype6 libexpat1 \
    && rm -rf /var/lib/apt/lists/*

# Install the CLI, SDK and REST service from the same source package.
COPY . .
RUN pip install --no-cache-dir . && playwright install chromium \
    && chmod -R a+rX /opt/playwright-browsers

# Create data directory for downloads
RUN mkdir -p /app/data/images /app/session && chmod 700 /app/session

# Non-root user
RUN groupadd -r appuser && useradd -r -g appuser -d /app -s /sbin/nologin appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8010

HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8010/health')" || exit 1

ENV HEADLESS=true
ENV PORT=8010
ENV HOST=0.0.0.0
ENV XHH_OPERATOR_HOME=/app/session

CMD ["python", "api_server.py"]
