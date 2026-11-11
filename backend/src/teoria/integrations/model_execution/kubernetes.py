"""Native async Kubernetes HTTP execution with namespaced resources and fixed privileges."""
from __future__ import annotations

import asyncio
import hashlib
import json
import sys
from pathlib import Path
import ssl
import time

import httpx


def container_manifest(spec, environment, settings):
    settings.validate_image(spec.image)
    resources = {"cpu": str(spec.resources.cpu), "memory": f"{spec.resources.memory_mib}Mi"}
    if spec.resources.gpu:
        resources["nvidia.com/gpu"] = str(spec.resources.gpu)
    return {
        "name": "model", "image": spec.image, "command": spec.command,
        "env": [{"name": key, "value": str(value)} for key, value in environment.items()],
        "envFrom": [{"secretRef": {"name": settings.workload_secret}}],
        "resources": {"requests": resources, "limits": resources.copy()},
        "securityContext": {"allowPrivilegeEscalation": False, "runAsNonRoot": True,
                            "runAsUser": 10001, "runAsGroup": 10001, "capabilities": {"drop": ["ALL"]},
                            "seccompProfile": {"type": "RuntimeDefault"}},
    }


def pod_manifest(container, settings):
    return {"automountServiceAccountToken": False, "restartPolicy": "Never",
            "imagePullSecrets": [{"name": settings.image_pull_secret}], "containers": [container]}


def training_manifest(spec, run_id, settings):
    name = "model-training-" + hashlib.sha256(run_id.encode()).hexdigest()[:20]
    container = container_manifest(spec, {
        "MLFLOW_TRACKING_URI": settings.mlflow_url,
        "TEORIA_MODEL_NAME": spec.model_name, "TEORIA_TRAINING_RUN_ID": run_id,
        "TEORIA_INPUT_SHA256": spec.input_sha256, "TEORIA_INPUT_URI": spec.input_uri, "TEORIA_OUTPUT_URI": spec.output_uri,
        "TEORIA_TRAINING_PARAMETERS": json.dumps(spec.parameters),
    }, settings)
    return {"apiVersion": "batch/v1", "kind": "Job", "metadata": {"name": name},
            "spec": {"backoffLimit": 0, "activeDeadlineSeconds": spec.timeout_seconds,
                     "ttlSecondsAfterFinished": 3600,
                     "template": {"spec": pod_manifest(container, settings)}}}


def serving_manifest(spec, settings):
    name = "model-serving-" + spec.deployment_id
    labels = {"app.kubernetes.io/managed-by": "teoria-mlops", "teoria-deployment": spec.deployment_id}
    container = container_manifest(spec, {
        "MLFLOW_TRACKING_URI": settings.mlflow_url,
        "TEORIA_MODEL_NAME": spec.model_name, "TEORIA_MODEL_VERSION": spec.model_version,
        "TEORIA_MODEL_URI": f"models:/{spec.model_name}/{spec.model_version}",
        "TEORIA_MODEL_SHA256": spec.model_sha256, "PORT": "8080",
    }, settings)
    container["ports"] = [{"containerPort": 8080}]
    container["readinessProbe"] = {"httpGet": {"path": spec.readiness_path, "port": 8080}, "periodSeconds": 2}
    pod = pod_manifest(container, settings)
    pod["restartPolicy"] = "Always"
    deployment = {"apiVersion": "apps/v1", "kind": "Deployment", "metadata": {"name": name, "labels": labels},
        "spec": {"replicas": spec.replicas, "progressDeadlineSeconds": max(60, spec.readiness_timeout_seconds),
                 "strategy": {"type": "RollingUpdate", "rollingUpdate": {"maxUnavailable": 0, "maxSurge": 1}},
                 "selector": {"matchLabels": labels}, "template": {"metadata": {"labels": labels}, "spec": pod}}}
    service = {"apiVersion": "v1", "kind": "Service", "metadata": {"name": name, "labels": labels},
               "spec": {"selector": labels, "ports": [{"port": 8080, "targetPort": 8080}]}}
    return deployment, service


class KubernetesExecutor:
    def __init__(self, settings, http=None, log_handler=None):
        self.settings = settings
        self.owns_http = http is None
        self.log_handler = log_handler
        self.http = http or httpx.AsyncClient(base_url=settings.kubernetes_url,
            verify=ssl.create_default_context(cafile=settings.kubernetes_ca_file), timeout=30, trust_env=False)

    async def close(self):
        if self.owns_http:
            await self.http.aclose()

    async def request(self, method, path, body=None, *, missing_ok=False):
        headers = {"Authorization": "Bearer " + Path(self.settings.kubernetes_token_file).read_text().strip()}
        if method == "PATCH":
            headers["Content-Type"] = "application/merge-patch+json"
        response = await self.http.request(method, path, json=body, headers=headers)
        if missing_ok and response.status_code == 404:
            return None
        response.raise_for_status()
        return response.json()

    def path(self, resource, name=None):
        api = "apps/v1" if resource == "deployments" else "batch/v1" if resource == "jobs" else None
        return (f"/apis/{api}" if api else "/api/v1") + f"/namespaces/{self.settings.namespace}/{resource}" + (f"/{name}" if name else "")

    async def apply(self, resource, manifest):
        path = self.path(resource, manifest["metadata"]["name"])
        existing = await self.request("GET", path, missing_ok=True)
        if existing is not None:
            if existing["metadata"].get("labels", {}).get("app.kubernetes.io/managed-by") != "teoria-mlops":
                raise ValueError("Kubernetes object is not owned by Teoria MLOps")
            return await self.request("PATCH", path, manifest)
        return await self.request("POST", self.path(resource), manifest)

    async def train(self, spec, run_id):
        job = training_manifest(spec, run_id, self.settings)
        name = job["metadata"]["name"]
        job["metadata"]["labels"] = {"app.kubernetes.io/managed-by": "teoria-mlops"}
        owned = False
        try:
            await self.apply("jobs", job)
            owned = True
            deadline = time.monotonic() + spec.timeout_seconds + 60
            while time.monotonic() < deadline:
                state = await self.request("GET", self.path("jobs", name))
                if state.get("status", {}).get("succeeded"):
                    return {"output_uri": spec.output_uri, "image": spec.image, "exit_code": 0}
                if state.get("status", {}).get("failed"):
                    raise RuntimeError("Kubernetes training Job failed; inspect its Pod logs")
                await asyncio.sleep(2)
            raise TimeoutError("Training Job exceeded its configured deadline")
        finally:
            if owned:
                failed = sys.exc_info()[0] is not None
                try:
                    if self.log_handler:
                        pods = await self.request("GET", self.path("pods") + "?labelSelector=job-name%3D" + name)
                        logs = bytearray()
                        for pod in pods.get("items", [])[:4]:
                            response = await self.http.get(self.path("pods", pod["metadata"]["name"]) + "/log",
                                params={"limitBytes": 1024*1024, "timestamps": "true"},
                                headers={"Authorization":"Bearer " + Path(self.settings.kubernetes_token_file).read_text().strip()})
                            logs.extend(response.content if response.is_success else b"Workload logs unavailable\n")
                        await self.log_handler(run_id, bytes(logs))
                except Exception:
                    if not failed:
                        raise RuntimeError("Workload completed but its logs could not be preserved") from None
                finally:
                    await self.request("DELETE", self.path("jobs", name), {"propagationPolicy": "Background"}, missing_ok=True)

    async def deploy(self, spec, run_id):
        deployment, service = serving_manifest(spec, self.settings)
        name = deployment["metadata"]["name"]
        previous = await self.request("GET", self.path("deployments", name), missing_ok=True)
        if previous and previous["metadata"].get("labels", {}).get("app.kubernetes.io/managed-by") != "teoria-mlops":
            raise ValueError("Kubernetes object is not owned by Teoria MLOps")
        try:
            await self.apply("services", service)
            applied = await self.apply("deployments", deployment)
            generation = applied["metadata"]["generation"]
            deadline = time.monotonic() + spec.readiness_timeout_seconds
            while time.monotonic() < deadline:
                current = await self.request("GET", self.path("deployments", name))
                state = current.get("status", {})
                if state.get("observedGeneration", 0) >= generation and state.get("replicas", 0) == spec.replicas and state.get("updatedReplicas", 0) == spec.replicas and state.get("availableReplicas", 0) >= spec.replicas:
                    return {"endpoint": f"http://{name}.{self.settings.namespace}.svc:8080", "image": spec.image}
                await asyncio.sleep(2)
            raise TimeoutError("Kubernetes serving rollout did not become ready")
        except BaseException:
            if previous:
                await self.request("PATCH", self.path("deployments", name), {"spec": previous["spec"]})
            else:
                await self.stop(spec.deployment_id)
            raise

    async def stop(self, deployment_id):
        name = "model-serving-" + deployment_id
        for resource in ("deployments", "services"):
            existing = await self.request("GET", self.path(resource, name), missing_ok=True)
            if existing is not None:
                if existing["metadata"].get("labels", {}).get("app.kubernetes.io/managed-by") != "teoria-mlops":
                    raise ValueError("Kubernetes object is not owned by Teoria MLOps")
                await self.request("DELETE", self.path(resource, name), {"propagationPolicy": "Background"}, missing_ok=True)
