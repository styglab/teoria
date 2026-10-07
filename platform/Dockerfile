FROM python:3.12-slim AS base

COPY --from=ghcr.io/astral-sh/uv:0.12.0 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

COPY pyproject.toml uv.lock ./
COPY platform/pyproject.toml ./platform/pyproject.toml
COPY pipelines/pyproject.toml ./pipelines/pyproject.toml
COPY mcp/pyproject.toml ./mcp/pyproject.toml
COPY packages/provider_api/pyproject.toml ./packages/provider_api/pyproject.toml
COPY packages/provider_api/src ./packages/provider_api/src
COPY platform/src ./platform/src

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --package teoria-platform --no-dev --no-editable

RUN useradd --create-home --uid 10001 teoria

FROM base AS runtime
COPY --chown=teoria:teoria platform/registries ./platform/registries
USER teoria
ENV TEORIA_REGISTRY_PATH=/app/platform/registries
CMD ["teoria-runtime-api"]

FROM runtime AS authoring
USER root
COPY --chown=teoria:teoria platform/ontology_migrations ./platform/ontology_migrations
COPY --chown=teoria:teoria platform/references ./platform/references
COPY --chown=teoria:teoria platform/database ./platform/database
USER teoria
CMD ["teoria", "validate", "/app/platform/registries"]
