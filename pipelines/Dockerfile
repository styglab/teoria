FROM python:3.12-slim AS base

COPY --from=ghcr.io/astral-sh/uv:0.12.0 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

COPY pyproject.toml uv.lock ./
COPY packages/provider/pyproject.toml ./packages/provider/pyproject.toml
COPY platform/pyproject.toml ./platform/pyproject.toml
COPY pipelines/pyproject.toml ./pipelines/pyproject.toml
COPY mcp/pyproject.toml ./mcp/pyproject.toml
COPY packages/provider/src ./packages/provider/src
COPY pipelines/src ./pipelines/src

FROM base AS worker

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --package teoria-pipelines --no-dev --group orchestration --no-editable

RUN useradd --create-home --uid 10001 teoria
COPY --chown=teoria:teoria pipelines/connectors ./pipelines/connectors
COPY --chown=teoria:teoria pipelines/definitions ./pipelines/definitions
COPY --chown=teoria:teoria pipelines/references ./pipelines/references
COPY --chown=teoria:teoria pipelines/database ./pipelines/database
COPY --chown=teoria:teoria pipelines/prefect.yaml ./pipelines/prefect.yaml

USER teoria
ENV TEORIA_PIPELINE_PATH=/app/pipelines
CMD ["prefect", "worker", "start", "--pool", "teoria-ingestion"]

FROM base AS check

COPY platform/src ./platform/src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --package teoria-pipelines --no-dev --group validation --no-editable

RUN useradd --create-home --uid 10001 teoria
COPY --chown=teoria:teoria pipelines/connectors ./pipelines/connectors
COPY --chown=teoria:teoria pipelines/definitions ./pipelines/definitions
COPY --chown=teoria:teoria pipelines/verification_cases ./pipelines/verification_cases
COPY --chown=teoria:teoria pipelines/references ./pipelines/references
COPY --chown=teoria:teoria pipelines/database ./pipelines/database
COPY --chown=teoria:teoria platform/registries ./platform/registries
COPY --chown=teoria:teoria platform/references ./platform/references

USER teoria
ENV TEORIA_PIPELINE_PATH=/app/pipelines \
    TEORIA_PLATFORM_REGISTRY_PATH=/app/platform/registries
CMD ["teoria-pipelines", "validate-integration", "/app/pipelines", "--platform-registries", "/app/platform/registries"]
