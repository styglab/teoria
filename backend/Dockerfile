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

FROM runtime AS authoring
USER root
COPY --from=model_cli /usr/local/bin/node /usr/local/bin/node
COPY --from=model_cli /usr/local/lib/node_modules/@openai /opt/codex/node_modules/@openai
RUN ln -s /opt/codex/node_modules/@openai/codex/bin/codex.js /usr/local/bin/codex && \
    mkdir -p /home/teoria/.codex /app/specification_inputs /app/specification_artifacts && chown teoria:teoria /home/teoria/.codex /app/specification_inputs /app/specification_artifacts
COPY --chown=teoria:teoria backend/authoring/ontology_migrations ./backend/authoring/ontology_migrations
COPY --chown=teoria:teoria backend/authoring/ontology_blueprints ./backend/authoring/ontology_blueprints
COPY --chown=teoria:teoria backend/authoring/normalization_profiles ./backend/authoring/normalization_profiles
COPY --chown=teoria:teoria backend/references ./backend/references
COPY --chown=teoria:teoria backend/migrations/application ./backend/migrations/application
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
COPY --chown=teoria:teoria deploy/k3s/prefect ./deploy/k3s/prefect
ENV TEORIA_PIPELINE_PATH=/app/backend

FROM data-operations AS law-worker
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --project backend --locked --no-dev --group orchestration --no-editable
USER teoria
CMD ["teoria-pipelines", "worker", "--pool", "teoria-legal-information"]

FROM data-operations AS worker
COPY --from=model_cli /usr/local/bin/node /usr/local/bin/node
COPY --from=model_cli /usr/local/lib/node_modules/@openai /opt/codex/node_modules/@openai
RUN ln -s /opt/codex/node_modules/@openai/codex/bin/codex.js /usr/local/bin/codex
# The archived parser remains a separate executable and environment.
COPY archive/kory_parser/pyproject.toml archive/kory_parser/uv.lock /opt/kory_parser_source/
COPY archive/kory_parser/src /opt/kory_parser_source/src
COPY archive/kory_parser/third_party /opt/kory_parser_source/third_party
RUN UV_PROJECT_ENVIRONMENT=/opt/kory_parser uv sync --project /opt/kory_parser_source --locked --no-dev
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

# Optional MLOps processes do not contain the document parser or Codex CLI.
FROM data-operations AS model-worker
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --project backend --locked --no-dev --extra api --group orchestration --group model-operations --no-editable
USER teoria
CMD ["prefect", "worker", "start", "--pool", "teoria-model-training"]
