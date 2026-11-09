"""Async verification of issuer-signed API access tokens; no token-supplied URLs."""
from __future__ import annotations

import asyncio
import time
from urllib.parse import quote, urlsplit

import httpx
import jwt

from teoria.settings import Settings


class OidcVerifier:
    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None):
        self.issuer = settings.admin_oidc_issuer
        self.audience = settings.admin_oidc_audience
        self.jwks_url = settings.admin_oidc_jwks_url
        for value in (self.issuer, self.jwks_url):
            url = urlsplit(value or "")
            if url.scheme != "https" or not url.netloc or url.username or url.password or url.fragment:
                raise ValueError("OIDC issuer and JWKS must be explicitly configured HTTPS URLs")
        if not self.audience or settings.admin_auth_mode != "bearer":
            raise ValueError("OIDC requires bearer authentication and an API audience")
        self.claim = settings.admin_oidc_roles_claim.split(".")
        if not all(self.claim):
            raise ValueError("OIDC roles claim path must not be empty")
        self.mapping = settings.admin_oidc_role_mapping
        self.client = client or httpx.AsyncClient(timeout=5, follow_redirects=False)
        self.owns_client = client is None
        self.lock = asyncio.Lock()
        self.keys: list[dict] = []
        self.refresh_at = 0.0
        self.retry_at = 0.0

    async def close(self):
        if self.owns_client:
            await self.client.aclose()

    async def _key(self, kid):
        async with self.lock:
            now = time.monotonic()
            found = next((k for k in self.keys if k.get("kid") == kid), None)
            if now >= self.refresh_at or (found is None and now >= self.retry_at):
                # Bound refreshes for unknown key IDs; do not use stale keys after expiry.
                if now < self.retry_at:
                    raise jwt.InvalidTokenError("JWKS refresh unavailable")
                self.retry_at = now + 10
                response = await self.client.get(self.jwks_url)
                response.raise_for_status()
                body = response.json()
                keys = body.get("keys") if isinstance(body, dict) else None
                if not isinstance(keys, list) or len(keys) > 100:
                    raise jwt.InvalidTokenError("Invalid key set")
                self.keys = [k for k in keys if isinstance(k, dict)
                             and k.get("kty") == "RSA" and k.get("use", "sig") == "sig"
                             and k.get("alg", "RS256") == "RS256"
                             and "verify" in k.get("key_ops", ["verify"])]
                self.refresh_at = now + 300
                found = next((k for k in self.keys if k.get("kid") == kid), None)
            matches = [k for k in self.keys if k.get("kid") == kid]
            if len(matches) != 1 or found is None:
                raise jwt.InvalidTokenError("Unknown signing key")
            return jwt.PyJWK.from_dict(found, algorithm="RS256").key

    async def verify(self, token: str) -> tuple[str, frozenset[str]]:
        if len(token) > 16384:
            raise jwt.InvalidTokenError("Token too large")
        header = jwt.get_unverified_header(token)
        if header.get("alg") != "RS256" or not isinstance(header.get("kid"), str) or header.get("crit"):
            raise jwt.InvalidTokenError("Unsupported token header")
        key = await self._key(header["kid"])
        claims = jwt.decode(token, key, algorithms=["RS256"], issuer=self.issuer,
                            audience=self.audience, options={"require": ["exp", "iat", "iss", "aud", "sub"]})
        if not isinstance(claims["sub"], str) or not claims["sub"] or len(claims["sub"]) > 512:
            raise jwt.InvalidTokenError("Invalid subject")
        roles = claims
        for part in self.claim:
            roles = roles.get(part) if isinstance(roles, dict) else None
        if roles is None:
            roles = []
        if not isinstance(roles, list) or any(not isinstance(role, str) for role in roles):
            raise jwt.InvalidTokenError("Invalid roles claim")
        local = frozenset(role for external in roles for role in self.mapping.get(external, []))
        # Issuer plus immutable subject prevents collisions between tenants and humans/services.
        actor = "oidc:" + quote(self.issuer, safe="") + ":" + quote(claims["sub"], safe="")
        return actor, local
