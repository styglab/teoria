FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.12.0 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

COPY pyproject.toml uv.lock ./
COPY platform/pyproject.toml ./platform/pyproject.toml
COPY pipelines/pyproject.toml ./pipelines/pyproject.toml
COPY mcp/pyproject.toml ./mcp/pyproject.toml
COPY packages/provider/pyproject.toml ./packages/provider/pyproject.toml
COPY mcp/src ./mcp/src

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --package teoria-mcp --no-dev --no-editable

RUN useradd --create-home --uid 10001 teoria
USER teoria
ENV TEORIA_MCP_RUNTIME_MODE=remote
CMD ["teoria-mcp"]
