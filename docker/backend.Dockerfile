# syntax=docker/dockerfile:1.6

FROM python:3.12-slim AS builder
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
WORKDIR /build

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY backend/pyproject.toml ./pyproject.toml

RUN python - <<'PY'
import pathlib
import tomllib
pyproject = pathlib.Path('pyproject.toml')
config = tomllib.loads(pyproject.read_text())
deps = config.get('project', {}).get('dependencies', [])
pathlib.Path('requirements.txt').write_text('\n'.join(deps))
PY

RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --upgrade pip \
    && /opt/venv/bin/pip install --no-cache-dir -r requirements.txt


FROM python:3.12-slim AS runtime
ARG APP_UID=1000
ARG APP_GID=1000
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH="/app/backend"

RUN groupadd --system --gid "${APP_GID}" app \
    && useradd --system --no-create-home --uid "${APP_UID}" --gid app app

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
COPY backend /app/backend

RUN mkdir -p /app/logs /app/data \
    && chown -R app:app /app

USER app

EXPOSE 8001

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
