"""Render the deployment inventory from the versioned Prefect manifests."""

from pathlib import Path
from typing import Any


from teoria.integrations.prefect.deployment_manifests import (
    DEPLOYMENT_FILES,
    deployment_path,
    load_deployment_manifest,
)


def load_deployments(
    pipeline_root: Path, backend: str = "process"
) -> list[tuple[Path, dict[str, Any]]]:
    return [
        (deployment_path(pipeline_root, kind, backend), deployment)
        for kind in sorted(DEPLOYMENT_FILES)
        if deployment_path(pipeline_root, kind, backend).is_file()
        for deployment in load_deployment_manifest(pipeline_root, kind, backend)[
            "deployments"
        ]
    ]


def render_deployment_docs(pipeline_root: Path) -> str:
    lines = [
        "# Pipeline Deployment 목록",
        "",
        "이 표는 `backend/config/*/prefect_deployments.yaml`과 `deploy/{compose,k3s}/prefect/*.yaml`에서 생성한다. 수동으로 수정하지 않는다.",
        "저장소에 선언된 설정이며 실행 중인 Prefect Server 상태를 조회한 결과는 아니다.",
        "",
        "```bash",
        "uv run --locked --project backend teoria-pipelines deployment-docs > docs/pipelines/deployments.md",
        "uv run --locked --project backend teoria-pipelines deployment-docs --check docs/pipelines/deployments.md",
        "```",
        "",
    ]
    for backend, environment in (("process", "Compose"), ("kubernetes", "K3s")):
        lines.extend([f"## {environment}", ""])
        for path, deployment in load_deployments(pipeline_root, backend):
            name = deployment["name"]
            lines.extend(
                [
                    f"### `{name}`",
                    "",
                    deployment["description"],
                    "",
                    f"- 환경 설정: `{path.relative_to(pipeline_root.resolve().parent).as_posix()}`",
                    f"- 공통 선언: `backend/config/{path.stem}/prefect_deployments.yaml`",
                    f"- Flow: `{deployment['entrypoint']}`",
                    f"- Work pool: `{deployment['work_pool']['name']}`",
                    f"- Work queue: `{deployment['work_pool']['work_queue_name']}`",
                ]
            )
            contracts = [
                tag.removeprefix("pipeline:")
                for tag in deployment.get("tags", [])
                if tag.startswith("pipeline:")
            ]
            if contracts:
                lines.append(
                    "- 수집 계약: " + ", ".join(f"`{value}`" for value in contracts)
                )
            parameters = deployment.get("parameters", {})
            if parameters:
                values = ", ".join(
                    f"`{key}={value}`" for key, value in parameters.items()
                )
                lines.append(f"- 파라미터: {values}")
            lines.extend(["", "| Cron | Timezone | 예약 상태 |", "|---|---|---|"])
            for schedule in deployment.get("schedules", []):
                state = "활성" if schedule.get("active", True) else "비활성"
                lines.append(
                    f"| `{schedule['cron']}` | `{schedule['timezone']}` | {state} |"
                )
            if not deployment.get("schedules"):
                lines.append("| — | — | 수동 실행 |")
            lines.append("")
    return "\n".join(lines)
