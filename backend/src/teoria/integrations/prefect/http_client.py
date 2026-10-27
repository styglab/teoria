"""Native async Prefect management calls; credentials stay on the server."""

from datetime import datetime, timezone

import httpx


class PrefectManagementClient:
    def __init__(self, client: httpx.AsyncClient, url: str, auth_string: str):
        self.client, self.url = client, url.rstrip("/")
        username, password = auth_string.split(":", 1)
        self.auth = httpx.BasicAuth(username, password)

    async def request(self, method: str, path: str, body: dict):
        response = await self.client.request(
            method,
            self.url + path,
            json=body if method != "GET" else None,
            auth=self.auth,
        )
        response.raise_for_status()
        return response.json() if response.content else None

    async def deployments(self, names: list[str]):
        return await self.request(
            "POST",
            "/deployments/filter",
            {"deployments": {"name": {"any_": names}}, "limit": 20},
        )

    def run_filters(self, ids: list[str], state: str | None = None) -> dict:
        criteria = (
            {"state": {"type": {"any_": [state]}}}
            if state
            else {
                "operator": "or_",
                "state": {"type": {"not_any_": ["SCHEDULED"]}},
                "expected_start_time": {
                    "before_": datetime.now(timezone.utc).isoformat()
                },
            }
        )
        return {"deployments": {"id": {"any_": ids}}, "flow_runs": criteria}

    async def runs(
        self,
        ids: list[str],
        *,
        limit: int = 25,
        offset: int = 0,
        state: str | None = None,
    ):
        if not ids:
            return []
        return await self.request(
            "POST",
            "/flow_runs/filter",
            {
                **self.run_filters(ids, state),
                "limit": limit,
                "offset": offset,
                "sort": "EXPECTED_START_TIME_DESC",
            },
        )

    async def run_count(self, ids: list[str], state: str | None = None):
        if not ids:
            return 0
        return await self.request(
            "POST", "/flow_runs/count", self.run_filters(ids, state)
        )

    async def next_run(self, identifier: str):
        return await self.request(
            "POST",
            "/flow_runs/filter",
            {
                "deployments": {"id": {"any_": [identifier]}},
                "flow_runs": {
                    "state": {"type": {"any_": ["SCHEDULED"]}},
                    "expected_start_time": {
                        "after_": datetime.now(timezone.utc).isoformat()
                    },
                },
                "limit": 1,
                "sort": "EXPECTED_START_TIME_ASC",
            },
        )

    async def update_schedule(
        self, deployment_id: str, schedule_id: str, updates: dict
    ):
        return await self.request(
            "PATCH", f"/deployments/{deployment_id}/schedules/{schedule_id}", updates
        )

    async def cancel_run(self, identifier: str, actor: str):
        return await self.request(
            "POST",
            f"/flow_runs/{identifier}/set_state",
            {
                "state": {
                    "type": "CANCELLING",
                    "name": "Cancelling",
                    "message": f"Cancellation requested by {actor}",
                },
                "force": False,
            },
        )

    async def run(self, identifier: str):
        return await self.request("GET", f"/flow_runs/{identifier}", {})

    async def subflows(self, identifier: str):
        return await self.request(
            "POST",
            "/flow_runs/filter",
            {
                "flow_runs": {"parent_flow_run_id": {"any_": [identifier]}},
                "limit": 50,
                "sort": "EXPECTED_START_TIME_ASC",
            },
        )

    async def tasks(self, identifier: str):
        return await self.request(
            "POST",
            "/task_runs/filter",
            {
                "flow_runs": {"id": {"any_": [identifier]}},
                "limit": 100,
                "sort": "EXPECTED_START_TIME_ASC",
            },
        )

    async def logs(self, identifier: str):
        return await self.request(
            "POST",
            "/logs/filter",
            {
                "logs": {"flow_run_id": {"any_": [identifier]}},
                "limit": 100,
                "sort": "TIMESTAMP_DESC",
            },
        )

    async def create_run(
        self, deployment_id: str, parameters: dict, *, actor: str, key: str
    ):
        return await self.request(
            "POST",
            f"/deployments/{deployment_id}/create_flow_run",
            {
                "parameters": parameters,
                "idempotency_key": key,
                "tags": ["teoria:admin-ui", f"teoria:actor:{actor}"],
            },
        )
