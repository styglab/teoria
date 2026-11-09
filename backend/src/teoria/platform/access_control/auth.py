from __future__ import annotations

import secrets
from dataclasses import dataclass
import httpx
import jwt

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from teoria.settings import Settings


@dataclass(frozen=True)
class AdminPrincipal:
    actor: str
    roles: frozenset[str]


class AdminAuthorizer:
    """Authentication and role checks at the Admin API boundary.

    Disabled mode is intentionally limited to local/development compatibility.
    Configured OIDC uses verified issuer/subject identities and explicit local
    role mappings. A shared bearer credential is never an OIDC fallback.
    """

    def __init__(self, settings: Settings, *, oidc_client: httpx.AsyncClient | None = None) -> None:
        self.mode = settings.admin_auth_mode
        self.token = settings.admin_api_token
        self.actor = settings.admin_api_actor
        self.roles = frozenset(role.strip() for role in settings.admin_api_roles.split(",") if role.strip())
        self.oidc = None
        if settings.admin_oidc_issuer:
            from teoria.platform.access_control.oidc import OidcVerifier
            self.oidc = OidcVerifier(settings, oidc_client)
        elif settings.admin_oidc_audience or settings.admin_oidc_jwks_url:
            raise ValueError("OIDC issuer is required")
        if self.mode == "bearer" and not self.token and self.oidc is None:
            raise ValueError("TEORIA_ADMIN_API_TOKEN is required when TEORIA_ADMIN_AUTH_MODE=bearer")
        self._bearer = HTTPBearer(auto_error=False)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        if self.oidc is not None:
            await self.oidc.close()

    def require(self, *required_roles: str):
        async def dependency(
            credentials: HTTPAuthorizationCredentials | None = Depends(self._bearer),
        ) -> AdminPrincipal:
            if self.mode == "bearer":
                supplied = credentials.credentials if credentials and credentials.scheme.lower() == "bearer" else ""
                if self.oidc is not None:
                    try:
                        actor, roles = await self.oidc.verify(supplied)
                        principal = AdminPrincipal(actor, roles)
                    except httpx.HTTPError:
                        raise HTTPException(status_code=503, detail={"code": "identity_provider_unavailable"}) from None
                    except (jwt.PyJWTError, ValueError, TypeError, KeyError):
                        raise HTTPException(status_code=401, detail={"code": "admin_authentication_required"}) from None
                elif not self.token or not secrets.compare_digest(supplied, self.token):
                    raise HTTPException(status_code=401, detail={"code": "admin_authentication_required"})
                else:
                    principal = AdminPrincipal(self.actor, self.roles)
            else:
                principal = AdminPrincipal(self.actor, self.roles)
            if (self.oidc is not None and not principal.roles) or (required_roles and not principal.roles.intersection(required_roles)):
                raise HTTPException(
                    status_code=403,
                    detail={"code": "admin_role_required", "required_roles": list(required_roles)},
                )
            return principal

        return dependency
