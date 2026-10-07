from __future__ import annotations

import uvicorn


def main() -> None:
    uvicorn.run(
        "teoria.policy.control_plane:app_factory",
        factory=True,
        host="0.0.0.0",
        port=8002,
    )


if __name__ == "__main__":
    main()
