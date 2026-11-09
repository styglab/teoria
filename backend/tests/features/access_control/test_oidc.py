"""Real RSA verification with a fake issuer HTTP endpoint, never real credentials."""
import json
import time

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import Depends, FastAPI
from teoria.features.access_control.auth import AdminAuthorizer
from teoria.settings import Settings


@pytest.fixture
def signing_key():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
    return key, {**jwk, 'kid': 'key_1', 'use': 'sig', 'alg': 'RS256'}


def config(**changes):
    return Settings(admin_auth_mode='bearer', admin_api_token='legacy-token',
        admin_oidc_issuer='https://identity.example/tenant', admin_oidc_audience='teoria-api',
        admin_oidc_jwks_url='https://identity.example/keys', admin_oidc_roles_claim='realm_access.roles',
        admin_oidc_role_mapping={'teoria-reviewers': ['binding_reviewer'], 'teoria-owners': ['ontology_owner']}, **changes)


def token(key, **changes):
    claims = {'iss': 'https://identity.example/tenant', 'aud': 'teoria-api', 'sub': 'alice',
              'iat': int(time.time()), 'exp': int(time.time()) + 300,
              'realm_access': {'roles': ['teoria-reviewers']}}
    return jwt.encode({**claims, **changes}, key, algorithm='RS256', headers={'kid': 'key_1'})


async def request(signing_key, value, *, role='binding_reviewer', transport=None):
    _, public = signing_key
    transport = transport or httpx.MockTransport(lambda _: httpx.Response(200, json={'keys': [public]}))
    async with httpx.AsyncClient(transport=transport) as identity:
        authorizer = AdminAuthorizer(config(), oidc_client=identity)
        app = FastAPI()
        @app.get('/review')
        async def review(principal=Depends(authorizer.require(role))):
            return {'actor': principal.actor, 'roles': sorted(principal.roles)}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            return await client.get('/review', headers={'Authorization': 'Bearer ' + value})


async def test_verified_subject_and_mapped_roles_ignore_default_actor_and_roles(signing_key):
    response = await request(signing_key, token(signing_key[0], actor='forged', roles=['ontology_owner']))
    assert response.status_code == 200
    assert response.json() == {'actor': 'oidc:https%3A%2F%2Fidentity.example%2Ftenant:alice', 'roles': ['binding_reviewer']}
    assert (await request(signing_key, token(signing_key[0]), role='ontology_owner')).status_code == 403
    service = await request(signing_key, token(signing_key[0], sub='worker:standards'))
    assert service.json()['actor'].endswith(':worker%3Astandards')


@pytest.mark.parametrize('changes', [
    {'aud': 'another-api'}, {'iss': 'https://attacker.example'}, {'exp': 1},
    {'sub': ''}, {'exp': None}, {'iat': None}, {'realm_access': {'roles': 'ontology_owner'}},
])
async def test_invalid_claims_are_rejected(signing_key, changes):
    assert (await request(signing_key, token(signing_key[0], **changes))).status_code == 401


async def test_forged_unsigned_and_legacy_tokens_are_rejected(signing_key):
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    for value in [token(other), 'legacy-token', jwt.encode({'sub': 'alice'}, '', algorithm='none')]:
        assert (await request(signing_key, value)).status_code == 401


async def test_key_cache_and_rotation_are_bounded(signing_key):
    calls = []
    def handler(req):
        calls.append(str(req.url))
        return httpx.Response(200, json={'keys': [signing_key[1]]})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        authorizer = AdminAuthorizer(config(), oidc_client=client)
        for _ in range(2):
            await authorizer.oidc.verify(token(signing_key[0]))
        with pytest.raises(jwt.InvalidTokenError):
            unknown = jwt.encode({'sub': 'alice'}, signing_key[0], algorithm='RS256', headers={'kid': 'unknown'})
            await authorizer.oidc.verify(unknown)
        assert calls == ['https://identity.example/keys']
        await authorizer.__aexit__()
        assert not client.is_closed


async def test_provider_failure_fails_closed(signing_key):
    transport = httpx.MockTransport(lambda _: httpx.Response(503))
    assert (await request(signing_key, token(signing_key[0]), transport=transport)).status_code == 503


def test_incomplete_or_insecure_settings_fail_at_startup():
    with pytest.raises(ValueError):
        AdminAuthorizer(Settings(admin_auth_mode='bearer', admin_oidc_issuer='http://issuer', admin_oidc_audience='api'))
    with pytest.raises(ValueError):
        AdminAuthorizer(Settings(admin_auth_mode='bearer', admin_api_token='token', admin_oidc_audience='api'))
