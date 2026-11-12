# Standalone validation workload: MLflow dependencies, no Teoria or Prefect code.
ARG MODEL_BASE=teoria-mlflow:0.1.0
FROM ${MODEL_BASE}
COPY --chown=10001:10001 model.py /app/model.py
USER 10001:10001
ENV PYTHONUNBUFFERED=1
EXPOSE 8080
CMD ["python", "/app/model.py", "serve"]
