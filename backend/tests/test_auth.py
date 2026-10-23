"""JWT authentication: app/auth.py and its enforcement on every REST route."""

import re
import time
import uuid

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec

from app import auth
from app.main import app

from .conftest import ISSUER, JWT_SECRET, make_token

PUBLIC_PATHS = {"/health", "/health/db", "/health/broker"}


def protected_routes() -> list[tuple[str, str]]:
    # From the OpenAPI schema: the public, complete list of REST routes the
    # app serves, however routers are nested internally.
    return [
        (method.upper(), path)
        for path, operations in app.openapi()["paths"].items()
        if path not in PUBLIC_PATHS
        for method in operations
    ]


@pytest.mark.parametrize(("method", "path"), protected_routes())
async def test_every_route_requires_a_token(client, method, path):
    # Guards against a new endpoint forgetting Depends(get_current_user).
    url = re.sub(r"\{[^}]+\}", str(uuid.uuid4()), path)
    response = await client.request(method, url, json={})
    assert response.status_code == 401, f"{method} {path} is reachable without a token"
    assert response.headers["www-authenticate"] == "Bearer"


def test_route_table_is_not_empty():
    # If routes were ever registered differently, the test above would
    # silently parametrize over nothing.
    assert len(protected_routes()) >= 15


def _expired() -> str:
    return make_token(uuid.uuid4(), expires_in=-120)  # beyond the 30s leeway


@pytest.mark.parametrize(
    "token",
    [
        pytest.param("not-a-jwt", id="garbage"),
        pytest.param(_expired(), id="expired"),
        pytest.param(make_token(uuid.uuid4(), aud="anon"), id="wrong-audience"),
        pytest.param(make_token(uuid.uuid4(), iss="https://evil.example/auth/v1"), id="wrong-issuer"),
        pytest.param(make_token(None), id="no-sub (anon/service key)"),
        pytest.param(make_token("not-a-uuid"), id="non-uuid-sub"),
        pytest.param(
            jwt.encode({"sub": str(uuid.uuid4()), "aud": "authenticated", "iss": ISSUER, "exp": int(time.time()) + 60},
                       "a-different-secret-of-sufficient-length!", algorithm="HS256"),
            id="wrong-secret",
        ),
        pytest.param(
            jwt.encode({"sub": str(uuid.uuid4()), "aud": "authenticated", "iss": ISSUER, "exp": int(time.time()) + 60},
                       None, algorithm="none"),
            id="alg-none",
        ),
        pytest.param(
            jwt.encode({"sub": str(uuid.uuid4()), "aud": "authenticated", "iss": ISSUER}, JWT_SECRET, algorithm="HS256"),
            id="no-exp",
        ),
    ],
)
async def test_invalid_tokens_are_rejected(client, token):
    response = await client.get("/workflows", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401
    assert response.json() == {"detail": "invalid or expired token"}


async def test_missing_bearer_token(client):
    response = await client.get("/workflows")
    assert response.status_code == 401
    assert response.json() == {"detail": "missing bearer token"}


async def test_valid_token_is_accepted(client, alice):
    response = await client.get("/workflows", headers=alice.headers)
    assert response.status_code == 200


def test_user_id_from_token_returns_sub():
    user_id = uuid.uuid4()
    assert auth.user_id_from_token(make_token(user_id)) == user_id


# --- Asymmetric (ES256) tokens via JWKS ---------------------------------------


class FakeJWKClient:
    def __init__(self, public_key):
        self._key = public_key

    def get_signing_key_from_jwt(self, token):
        return type("SigningKey", (), {"key": self._key})()


@pytest.fixture
def es256_key(monkeypatch):
    private = ec.generate_private_key(ec.SECP256R1())
    monkeypatch.setattr(auth, "_jwks_client", lambda: FakeJWKClient(private.public_key()))
    return private


def _es256(private, **claims):
    payload = {"aud": "authenticated", "iss": ISSUER, "exp": int(time.time()) + 60, **claims}
    return jwt.encode(payload, private, algorithm="ES256")


async def test_es256_token_verified_against_jwks(client, es256_key):
    user_id = uuid.uuid4()
    token = _es256(es256_key, sub=str(user_id))
    response = await client.get("/workflows", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200


async def test_es256_token_signed_by_another_key_is_rejected(client, es256_key):
    other = ec.generate_private_key(ec.SECP256R1())
    token = _es256(other, sub=str(uuid.uuid4()))
    response = await client.get("/workflows", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


async def test_es256_rejected_when_no_jwks_is_configured(client, monkeypatch):
    monkeypatch.setattr(auth, "_jwks_client", lambda: None)
    token = _es256(ec.generate_private_key(ec.SECP256R1()), sub=str(uuid.uuid4()))
    response = await client.get("/workflows", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401
