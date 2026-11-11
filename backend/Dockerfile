FROM node:22-bookworm-slim AS model_cli
RUN npm install --global @openai/codex@0.162.1

FROM python:3.12-slim AS base
COPY --from=ghcr.io/astral-sh/uv:0.12.0 /uv /uvx /bin/
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PATH="/app/backend/.venv/bin:$PATH"
WORKDIR /app
COPY backend/pyproject.toml backend/uv.lock ./backend/
COPY backend/src ./backend/src
RUN useradd --create-home --uid 10001 teoria

FROM base AS runtime
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --project backend --locked --no-dev --extra api --no-editable
COPY --chown=teoria:teoria backend/contracts/runtime ./backend/contracts/runtime
USER teoria
ENV TEORIA_REGISTRY_PATH=/app/backend/contracts/runtime
CMD ["teoria-runtime-api"]

FROM runtime AS admin
COPY --chown=teoria:teoria backend/config ./backend/config
COPY --chown=teoria:teoria deploy/compose/prefect ./deploy/compose/prefect
COPY --chown=teoria:teoria backend/authoring/ontology_migrations ./backend/authoring/ontology_migrations
COPY --chown=teoria:teoria backend/authoring/ontology_blueprints ./backend/authoring/ontology_blueprints
COPY --chown=teoria:teoria backend/authoring/normalization_profiles ./backend/authoring/normalization_profiles
COPY --chown=teoria:teoria backend/references ./backend/references
COPY --chown=teoria:teoria backend/migrations/application ./backend/migrations/application
CMD ["teoria-admin-api"]

FROM admin AS authoring
USER root
COPY --from=model_cli /usr/local/bin/node /usr/local/bin/node
COPY --from=model_cli /usr/local/lib/node_modules/@openai /opt/codex/node_modules/@openai
RUN ln -s /opt/codex/node_modules/@openai/codex/bin/codex.js /usr/local/bin/codex && \
    mkdir -p /home/teoria/.codex /app/specification_inputs /app/specification_artifacts && chown teoria:teoria /home/teoria/.codex /app/specification_inputs /app/specification_artifacts
USER teoria
CMD ["teoria-admin-api"]

FROM base AS data-operations
COPY --chown=teoria:teoria backend/contracts/ingestion/connectors ./backend/contracts/ingestion/connectors
COPY --chown=teoria:teoria backend/contracts/ingestion/pipelines ./backend/contracts/ingestion/pipelines
COPY --chown=teoria:teoria backend/config ./backend/config
COPY --chown=teoria:teoria backend/references ./backend/references
COPY --chown=teoria:teoria backend/verification_cases ./backend/verification_cases
COPY --chown=teoria:teoria backend/migrations/data ./backend/migrations/data
COPY --chown=teoria:teoria deploy/compose/prefect ./deploy/compose/prefect
COPY --chown=teoria:teoria deploy/kubernetes/prefect ./deploy/kubernetes/prefect
ENV TEORIA_PIPELINE_PATH=/app/backend

FROM data-operations AS operations
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --project backend --locked --no-dev --group orchestration --no-editable
USER teoria

FROM operations AS law-worker
CMD ["teoria-pipelines", "worker", "--pool", "teoria-legal-information"]

FROM data-operations AS worker
COPY --from=model_cli /usr/local/bin/node /usr/local/bin/node
COPY --from=model_cli /usr/local/lib/node_modules/@openai /opt/codex/node_modules/@openai
RUN ln -s /opt/codex/node_modules/@openai/codex/bin/codex.js /usr/local/bin/codex
# The archived parser remains a separate executable and environment.
COPY archive/kory_parser/pyproject.toml archive/kory_parser/uv.lock /opt/kory_parser_source/
COPY archive/kory_parser/src /opt/kory_parser_source/src
COPY archive/kory_parser/third_party /opt/kory_parser_source/third_party
RUN UV_PROJECT_ENVIRONMENT=/opt/kory_parser uv sync --project /opt/kory_parser_source --locked --no-dev --extra ocr
# Download PDF OCR models at build time: the runtime user cannot write to site-packages.
RUN /opt/kory_parser/bin/python - <<'PY'
import io
import pymupdf
from PIL import Image, ImageDraw, ImageFont
from kory_parser import parse, ParseOptions
image = Image.new('RGB', (640, 160), 'white')
ImageDraw.Draw(image).text((20, 50), 'OCR model initialization', fill='black', font=ImageFont.load_default(size=32))
stream = io.BytesIO()
image.save(stream, format='PNG')
document = pymupdf.open()
page = document.new_page(width=640, height=160)
page.insert_image(page.rect, stream=stream.getvalue())
assert parse(document.tobytes(), ParseOptions(ocr=True)).success
PY
ENV TEORIA_SPECIFICATION_PARSER_PYTHON=/opt/kory_parser/bin/python
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --project backend --locked --no-dev --group orchestration --no-editable
RUN mkdir -p /app/specification_inputs /app/specification_artifacts /home/teoria/.codex && \
    chown teoria:teoria /app/specification_inputs /app/specification_artifacts /home/teoria/.codex
USER teoria
CMD ["teoria-pipelines", "worker", "--pool", "teoria-specification"]

FROM worker AS kubernetes-worker
USER root
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --project backend --locked --no-dev --group orchestration --group kubernetes-orchestration --no-editable
USER teoria

FROM data-operations AS metadata-worker
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --project backend --locked --no-dev --group metadata-orchestration --no-editable
# Docker socket privileges are isolated to this worker; ingestion runs in its own image.
CMD ["prefect", "worker", "start", "--pool", "teoria-metadata"]

FROM base AS mcp
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --project backend --locked --no-dev --extra mcp --no-editable
USER teoria
ENV TEORIA_MCP_RUNTIME_MODE=remote
CMD ["teoria-mcp"]

FROM data-operations AS check
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --project backend --locked --no-dev --extra api --group orchestration --no-editable
COPY --chown=teoria:teoria backend/contracts/runtime ./backend/contracts/runtime
USER teoria
ENV TEORIA_PLATFORM_REGISTRY_PATH=/app/backend/contracts/runtime
CMD ["teoria-pipelines", "validate-integration", "/app/backend", "--platform-registries", "/app/backend/contracts/runtime"]

# MLflow only: no Teoria application, Prefect, document parser or Codex CLI.
FROM python:3.12-slim AS mlflow
COPY --from=ghcr.io/astral-sh/uv:0.12.0 /uv /bin/uv
ENV UV_LINK_MODE=copy PATH="/app/.venv/bin:$PATH"
WORKDIR /app
COPY backend/pyproject.toml backend/uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --only-group mlflow-server --no-install-project --no-editable && \
    useradd --create-home --uid 10001 teoria
USER teoria
CMD ["mlflow", "server", "--host", "0.0.0.0", "--port", "5000"]

# Dispatchers create ephemeral training containers without passing Docker access to jobs.
FROM data-operations AS model-dispatcher
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --project backend --locked --no-dev --group orchestration --group docker-orchestration --no-editable
CMD ["prefect", "worker", "start", "--pool", "teoria-model-operations", "--type", "process"]
