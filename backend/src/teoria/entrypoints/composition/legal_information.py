"""Legal information composition; feature policies remain in their owning packages."""
from __future__ import annotations

from typing import TYPE_CHECKING
from fastapi import FastAPI
from teoria.domains.legal_information.admin_router import create_law_search_router

if TYPE_CHECKING:
    from teoria.entrypoints.composition.admin import AdminServices


def install_legal_routers(app: FastAPI, services: AdminServices) -> None:
    if services.settings.legal_information_enabled:
        app.include_router(
            create_law_search_router(services.law_search_reader, services.authorizer)
        )
