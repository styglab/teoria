from __future__ import annotations

import secrets
from dataclasses import dataclass

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from teoria.config import Settings


@dataclass(frozen=True)
class AdminPrincipal:
    actor: str
    roles: frozenset[str]


class AdminAuthorizer:
    """Authentication and role checks at the Admin API boundary.

    Disabled mode is intentionally limited to local/development compatibility.
    Deployments can enable one shared bearer credential now without coupling the
    domain modules to a future identity provider.
    """

    def __init__(self, settings: Settings) -> None:
        self.mode = settings.admin_auth_mode
        self.token = settings.admin_api_token
        self.actor = settings.admin_api_actor
        self.roles = frozenset(role.strip() for role in settings.admin_api_roles.split(",") if role.strip())
        if self.mode == "bearer" and not self.token:
            raise ValueError("TEORIA_ADMIN_API_TOKEN is required when TEORIA_ADMIN_AUTH_MODE=bearer")
        self._bearer = HTTPBearer(auto_error=False)

    def require(self, *required_roles: str):
        async def dependency(
            credentials: HTTPAuthorizationCredentials | None = Depends(self._bearer),
        ) -> AdminPrincipal:
            if self.mode == "bearer":
                supplied = credentials.credentials if credentials and credentials.scheme.lower() == "bearer" else ""
                if not self.token or not secrets.compare_digest(supplied, self.token):
                    raise HTTPException(status_code=401, detail={"code": "admin_authentication_required"})
            principal = AdminPrincipal(self.actor, self.roles)
            if required_roles and not principal.roles.intersection(required_roles):
                raise HTTPException(
                    status_code=403,
                    detail={"code": "admin_role_required", "required_roles": list(required_roles)},
                )
            return principal

        return dependency
