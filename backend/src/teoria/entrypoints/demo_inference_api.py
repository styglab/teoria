"""Standalone demo inference process; never loaded into the Admin or Runtime API."""

from teoria.features.model_operations.inference import create_inference_app


def main():
    import uvicorn

    uvicorn.run(create_inference_app(), host="0.0.0.0", port=8003)
