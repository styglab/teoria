FROM node:22-bookworm-slim AS model_cli
RUN npm install --global @openai/codex@0.162.1

FROM python:3.12-slim AS base

COPY --from=ghcr.io/astral-sh/uv:0.12.0 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

COPY pyproject.toml uv.lock ./
COPY packages/provider_api/pyproject.toml ./packages/provider_api/pyproject.toml
COPY platform/pyproject.toml ./platform/pyproject.toml
COPY pipelines/pyproject.toml ./pipelines/pyproject.toml
COPY mcp/pyproject.toml ./mcp/pyproject.toml
COPY packages/provider_api/src ./packages/provider_api/src
COPY packages/goods_normalization/pyproject.toml ./packages/goods_normalization/pyproject.toml
COPY packages/codex_inference/pyproject.toml ./packages/codex_inference/pyproject.toml
COPY packages/codex_inference/src ./packages/codex_inference/src
COPY packages/goods_normalization/src ./packages/goods_normalization/src
COPY pipelines/src ./pipelines/src

FROM base AS worker

COPY --from=model_cli /usr/local/bin/node /usr/local/bin/node
COPY --from=model_cli /usr/local/lib/node_modules/@openai /opt/codex/node_modules/@openai
RUN ln -s /opt/codex/node_modules/@openai/codex/bin/codex.js /usr/local/bin/codex

# Parser stays an independently installed executable, outside the pipeline venv.
COPY archive/kory_parser/pyproject.toml archive/kory_parser/uv.lock /opt/kory_parser_source/
COPY archive/kory_parser/src /opt/kory_parser_source/src
COPY archive/kory_parser/third_party /opt/kory_parser_source/third_party
RUN UV_PROJECT_ENVIRONMENT=/opt/kory_parser uv sync --project /opt/kory_parser_source --locked --no-dev
ENV TEORIA_SPECIFICATION_PARSER_PYTHON=/opt/kory_parser/bin/python

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --package teoria-pipelines --no-dev --group orchestration --no-editable

RUN useradd --create-home --uid 10001 teoria && \
    mkdir -p /app/specification_inputs /app/specification_artifacts /home/teoria/.codex && \
    chown teoria:teoria /app/specification_inputs /app/specification_artifacts /home/teoria/.codex
COPY --chown=teoria:teoria pipelines/connectors ./pipelines/connectors
COPY --chown=teoria:teoria pipelines/definitions ./pipelines/definitions
COPY --chown=teoria:teoria pipelines/config ./pipelines/config
COPY --chown=teoria:teoria pipelines/references ./pipelines/references
COPY --chown=teoria:teoria pipelines/database ./pipelines/database
COPY --chown=teoria:teoria pipelines/prefect.yaml ./pipelines/prefect.yaml
COPY --chown=teoria:teoria pipelines/prefect.metadata.yaml ./pipelines/prefect.metadata.yaml
COPY --chown=teoria:teoria pipelines/prefect.legal_information.yaml ./pipelines/prefect.legal_information.yaml

USER teoria
ENV TEORIA_PIPELINE_PATH=/app/pipelines
CMD ["prefect", "worker", "start", "--pool", "teoria-specification"]

FROM worker AS kubernetes-worker

USER root
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --package teoria-pipelines --no-dev --group orchestration --group kubernetes-orchestration --no-editable
USER teoria

FROM base AS law-worker

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --package teoria-pipelines --no-dev --group orchestration --no-editable
RUN useradd --create-home --uid 10001 teoria
COPY --chown=teoria:teoria pipelines/connectors ./pipelines/connectors
COPY --chown=teoria:teoria pipelines/definitions ./pipelines/definitions
COPY --chown=teoria:teoria pipelines/config ./pipelines/config
COPY --chown=teoria:teoria pipelines/references ./pipelines/references
COPY --chown=teoria:teoria pipelines/verification_cases ./pipelines/verification_cases
COPY --chown=teoria:teoria pipelines/database ./pipelines/database
COPY --chown=teoria:teoria pipelines/prefect.legal_information.yaml ./pipelines/prefect.legal_information.yaml
USER teoria
ENV TEORIA_PIPELINE_PATH=/app/pipelines
CMD ["teoria-pipelines", "worker", "--pool", "teoria-legal-information"]

FROM base AS metadata-worker

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --package teoria-pipelines --no-dev --group metadata-orchestration --no-editable

COPY pipelines/connectors ./pipelines/connectors
COPY pipelines/definitions ./pipelines/definitions
COPY pipelines/config ./pipelines/config
COPY pipelines/references ./pipelines/references
COPY pipelines/database ./pipelines/database
COPY pipelines/prefect.yaml ./pipelines/prefect.yaml
COPY pipelines/prefect.metadata.yaml ./pipelines/prefect.metadata.yaml
COPY pipelines/prefect.legal_information.yaml ./pipelines/prefect.legal_information.yaml

# Docker socket access is intentionally isolated to this worker. The worker
# launches only the pinned OpenMetadata ingestion image and owns no connector
# implementation itself.
CMD ["prefect", "worker", "start", "--pool", "teoria-metadata"]

FROM base AS check

COPY platform/src ./platform/src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --package teoria-pipelines --no-dev --group validation --no-editable

RUN useradd --create-home --uid 10001 teoria && \
    mkdir -p /app/specification_inputs /app/specification_artifacts /home/teoria/.codex && \
    chown teoria:teoria /app/specification_inputs /app/specification_artifacts /home/teoria/.codex
COPY --chown=teoria:teoria pipelines/connectors ./pipelines/connectors
COPY --chown=teoria:teoria pipelines/definitions ./pipelines/definitions
COPY --chown=teoria:teoria pipelines/verification_cases ./pipelines/verification_cases
COPY --chown=teoria:teoria pipelines/config ./pipelines/config
COPY --chown=teoria:teoria pipelines/references ./pipelines/references
COPY --chown=teoria:teoria pipelines/database ./pipelines/database
COPY --chown=teoria:teoria platform/registries ./platform/registries
COPY --chown=teoria:teoria platform/references ./platform/references

USER teoria
ENV TEORIA_PIPELINE_PATH=/app/pipelines \
    TEORIA_PLATFORM_REGISTRY_PATH=/app/platform/registries
CMD ["teoria-pipelines", "validate-integration", "/app/pipelines", "--platform-registries", "/app/platform/registries"]
