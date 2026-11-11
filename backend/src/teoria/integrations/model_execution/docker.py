"""Bounded Docker SDK calls; jobs never receive the Docker socket or host mounts."""
from __future__ import annotations

import asyncio
import hashlib
import json
import sys
import time

import httpx


def serving_name(project, deployment_id):
    name = project + "-model-serving-" + deployment_id
    if len(name) <= 63:
        return name
    return "model-serving-" + hashlib.sha256((project+":"+deployment_id).encode()).hexdigest()[:40]


class DockerExecutor:
    def __init__(self, settings, client=None, http=None, log_handler=None):
        if client is None:
            import docker
            client = docker.from_env(timeout=30)
        self.client, self.settings = client, settings
        self.http = http or httpx.AsyncClient(timeout=5, trust_env=False)
        self.owns_http = http is None
        self.log_handler = log_handler

    async def close(self):
        await asyncio.to_thread(self.client.close)
        if self.owns_http:
            await self.http.aclose()

    async def create(self, spec, name, environment, role, run_id):
        import docker
        self.settings.validate_image(spec.image)
        try:
            await asyncio.to_thread(self.client.images.get, spec.image)
        except docker.errors.ImageNotFound:
            await asyncio.to_thread(self.client.images.pull, spec.image)
        resources = spec.resources
        return await asyncio.to_thread(
            self.client.containers.create, spec.image,
            entrypoint=spec.command[:1], command=spec.command[1:], name=name,
            environment={**self.settings.workload_environment, **environment},
            network=self.settings.network,
            labels={"io.teoria.project": self.settings.project, "io.teoria.role": role, "io.teoria.run": run_id},
            user="10001:10001", cap_drop=["ALL"], security_opt=["no-new-privileges:true"],
            mem_limit=f"{resources.memory_mib}m", memswap_limit=f"{resources.memory_mib}m",
            nano_cpus=int(resources.cpu * 1_000_000_000), pids_limit=256,
            log_config=docker.types.LogConfig(type="json-file", config={"max-size": "10m", "max-file": "2"}),
            device_requests=[docker.types.DeviceRequest(count=resources.gpu, capabilities=[["gpu"]])] if resources.gpu else [],
        )

    async def train(self, spec, run_id):
        environment = {
            "MLFLOW_TRACKING_URI": self.settings.mlflow_url,
            "TEORIA_MODEL_NAME": spec.model_name, "TEORIA_TRAINING_RUN_ID": run_id,
            "TEORIA_INPUT_SHA256": spec.input_sha256, "TEORIA_INPUT_URI": spec.input_uri, "TEORIA_OUTPUT_URI": spec.output_uri,
            "TEORIA_TRAINING_PARAMETERS": json.dumps(spec.parameters),
        }
        name = self.settings.project + "-model-training-" + hashlib.sha256(run_id.encode()).hexdigest()[:20]
        container = None
        try:
            container = await self.create(spec, name, environment, "model-training", run_id)
            await asyncio.to_thread(container.start)
            deadline = time.monotonic() + spec.timeout_seconds
            while time.monotonic() < deadline:
                await asyncio.to_thread(container.reload)
                if container.status in {"exited", "dead"}:
                    code = container.attrs["State"].get("ExitCode", 1)
                    if code != 0:
                        raise RuntimeError(f"Training container exited with code {code}")
                    return {"output_uri": spec.output_uri, "image": spec.image, "exit_code": code}
                await asyncio.sleep(1)
            raise TimeoutError("Training exceeded its configured deadline")
        finally:
            if container is not None:
                failed = sys.exc_info()[0] is not None
                try:
                    if self.log_handler:
                        data = await asyncio.to_thread(container.logs, stdout=True, stderr=True, tail=5000)
                        await self.log_handler(run_id, data[-4*1024*1024:])
                except Exception:
                    if not failed:
                        raise RuntimeError("Workload completed but its logs could not be preserved") from None
                finally:
                    await asyncio.to_thread(container.remove, force=True)

    async def owned_container(self, name):
        import docker
        try:
            container = await asyncio.to_thread(self.client.containers.get, name)
        except docker.errors.NotFound:
            return None
        labels = container.labels
        if labels.get("io.teoria.project") != self.settings.project or labels.get("io.teoria.role") != "model-serving":
            raise ValueError("Serving name belongs to an unmanaged container")
        return container

    async def deploy(self, spec, run_id):
        if spec.replicas != 1:
            raise ValueError("Docker development execution supports one serving replica; use Kubernetes for replicas")
        name = serving_name(self.settings.project, spec.deployment_id)
        previous = await self.owned_container(name)
        suffix = hashlib.sha256(run_id.encode()).hexdigest()[:12]
        candidate = None
        promoted = False
        retired = False
        try:
            candidate = await self.create(spec, name[:39] + "-candidate-" + suffix, {
                "MLFLOW_TRACKING_URI": self.settings.mlflow_url,
                "TEORIA_MODEL_NAME": spec.model_name,
                "TEORIA_MODEL_VERSION": str(spec.model_version),
                "TEORIA_MODEL_URI": f"models:/{spec.model_name}/{spec.model_version}",
                "TEORIA_MODEL_SHA256": spec.model_sha256,
                "PORT": "8080",
            }, "model-serving", run_id)
            await asyncio.to_thread(candidate.start)
            deadline = time.monotonic() + spec.readiness_timeout_seconds
            while True:
                try:
                    response = await self.http.get(f"http://{candidate.name}:8080{spec.readiness_path}")
                    response.raise_for_status()
                    break
                except httpx.HTTPError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError("Serving candidate did not become ready") from None
                    await asyncio.sleep(1)
            if previous is not None:
                await asyncio.to_thread(previous.rename, name[:39] + "-previous-" + suffix)
                retired = True
                await asyncio.to_thread(previous.stop, timeout=20)
            await asyncio.to_thread(candidate.rename, name)
            network = await asyncio.to_thread(self.client.networks.get, self.settings.network)
            await asyncio.to_thread(network.disconnect, candidate)
            await asyncio.to_thread(network.connect, candidate, aliases=[name])
            (await self.http.get(f"http://{name}:8080{spec.readiness_path}")).raise_for_status()
            promoted = True
            if previous is not None:
                await asyncio.to_thread(previous.remove, force=True)
            return {"endpoint": f"http://{name}:8080", "image": spec.image}
        finally:
            if not promoted:
                if candidate is not None:
                    await asyncio.to_thread(candidate.remove, force=True)
                if previous is not None and retired:
                    await asyncio.to_thread(previous.rename, name)
                    await asyncio.to_thread(previous.start)

    async def stop(self, deployment_id):
        container = await self.owned_container(serving_name(self.settings.project, deployment_id))
        if container is not None:
            await asyncio.to_thread(container.remove, force=True)
