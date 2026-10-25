"""Render the deployment inventory from the versioned Prefect manifests."""

from pathlib import Path
from typing import Any

import yaml


def load_deployments(pipeline_root: Path) -> list[tuple[Path, dict[str, Any]]]:
    return [
        (path, deployment)
        for path in sorted(pipeline_root.glob("prefect*.yaml"))
        for deployment in yaml.safe_load(path.read_text(encoding="utf-8"))[
            "deployments"
        ]
    ]


def render_deployment_docs(pipeline_root: Path) -> str:
    lines = [
        "# Pipeline Deployment 목록",
        "",
        "이 표는 `pipelines/prefect*.yaml`에서 생성한다. 수동으로 수정하지 않는다.",
        "저장소에 선언된 설정이며 실행 중인 Prefect Server 상태를 조회한 결과는 아니다.",
        "",
        "```bash",
        "uv run --locked --package teoria-pipelines teoria-pipelines deployment-docs > docs/pipelines/deployments.md",
        "uv run --locked --package teoria-pipelines teoria-pipelines deployment-docs --check docs/pipelines/deployments.md",
        "```",
        "",
    ]
    for path, deployment in load_deployments(pipeline_root):
        name = deployment["name"]
        lines.extend(
            [
                f"## `{name}`",
                "",
                deployment["description"],
                "",
                f"- 선언: `pipelines/{path.name}`",
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
            values = ", ".join(f"`{key}={value}`" for key, value in parameters.items())
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
