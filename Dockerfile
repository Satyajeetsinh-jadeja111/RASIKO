# ---- 1. Build the Tailwind CSS -------------------------------------------------------------------------------------
FROM node:22-alpine AS css
WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
COPY templates/ /build/templates/
COPY apps/ /build/apps/
COPY static/js/ /build/static/js/
RUN mkdir -p /build/static/css && npm run build

# ---- 2. Python app -----------------------------------------------------------------------------------------------
FROM python:3.12-slim AS app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DJANGO_SETTINGS_MODULE=config.settings.prod
RUN apt-get update && apt-get install -y --no-install-recommends libpq5 gettext curl postgresql-client \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 rasiko
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY --chown=rasiko:rasiko . .
COPY --from=css --chown=rasiko:rasiko /build/static/css/app.css static/css/app.css
# Asset commands load production settings; these temporary values exist only in this RUN.
RUN export DJANGO_SECRET_KEY=build-only-$(python -c "import secrets;print(secrets.token_hex(32))") \
    FIELD_ENCRYPTION_KEY=$(python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())") \
    && python manage.py collectstatic --noinput \
    && python manage.py compilemessages --ignore=venv --ignore=node_modules
RUN mkdir -p /app/media /app/logs /shared-static && chown -R rasiko:rasiko /app/media /app/logs /app/staticfiles /app/locale /shared-static
USER rasiko
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=10s --retries=3 CMD curl -fsS -H "Host: ${DOMAIN:-localhost}" http://localhost:8000/readyz || exit 1
ENTRYPOINT ["/app/docker/entrypoint.sh"]
CMD ["web"]
