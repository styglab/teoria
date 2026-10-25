FROM node:22-bookworm-slim AS model_cli
RUN npm install --global @openai/codex@0.162.1

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
COPY packages/goods_normalization/pyproject.toml ./packages/goods_normalization/pyproject.toml
COPY packages/codex_inference/pyproject.toml ./packages/codex_inference/pyproject.toml
COPY packages/codex_inference/src ./packages/codex_inference/src
COPY packages/goods_normalization/src ./packages/goods_normalization/src
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
COPY --from=model_cli /usr/local/bin/node /usr/local/bin/node
COPY --from=model_cli /usr/local/lib/node_modules/@openai /opt/codex/node_modules/@openai
RUN ln -s /opt/codex/node_modules/@openai/codex/bin/codex.js /usr/local/bin/codex && \
    mkdir -p /home/teoria/.codex && chown teoria:teoria /home/teoria/.codex
COPY --chown=teoria:teoria platform/ontology_migrations ./platform/ontology_migrations
COPY --chown=teoria:teoria platform/ontology_blueprints ./platform/ontology_blueprints
COPY --chown=teoria:teoria platform/references ./platform/references
COPY --chown=teoria:teoria platform/database ./platform/database
USER teoria
CMD ["teoria", "validate", "/app/platform/registries"]
