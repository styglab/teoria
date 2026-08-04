from __future__ import annotations

import uvicorn


def main() -> None:
    uvicorn.run("teoria.admin.api:app_factory", factory=True, host="0.0.0.0", port=8001)


if __name__ == "__main__":
    main()
