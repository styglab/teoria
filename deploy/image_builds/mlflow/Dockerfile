# syntax=docker/dockerfile:1.7.0
# MLflow only: no Teoria application, Prefect, document parser or Codex CLI.
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.12.0 /uv /bin/uv
ENV UV_LINK_MODE=copy PATH="/app/.venv/bin:$PATH"
WORKDIR /app
COPY backend/pyproject.toml backend/uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --only-group mlflow-server --no-install-project --no-editable && \
    useradd --create-home --uid 10001 teoria
USER teoria
CMD ["mlflow", "server", "--host", "0.0.0.0", "--port", "5000"]
