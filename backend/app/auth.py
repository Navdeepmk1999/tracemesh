import uuid
from functools import lru_cache
from typing import Annotated, Any

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import get_settings

ASYMMETRIC_ALGORITHMS = {"ES256", "RS256"}

bearer_scheme = HTTPBearer(auto_error=False)


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


@lru_cache
def _jwks_client() -> jwt.PyJWKClient | None:
    settings = get_settings()
    if not settings.supabase_url:
        return None
    # Caches fetched keys, so the network is only hit on first use or key rotation.
    return jwt.PyJWKClient(f"{settings.supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json")


def decode_supabase_jwt(token: str) -> dict[str, Any]:
    """Verify signature, expiry and audience; return the claims.

    The verification key is picked by algorithm, never taken from the token,
    so an HS256 token can't be checked against a public key (alg confusion).
    """
    settings = get_settings()
    alg = jwt.get_unverified_header(token).get("alg")

    if alg == "HS256":
        if not settings.supabase_jwt_secret:
            raise jwt.InvalidTokenError("HS256 tokens are not accepted: SUPABASE_JWT_SECRET is unset")
        key: Any = settings.supabase_jwt_secret
    elif alg in ASYMMETRIC_ALGORITHMS:
        client = _jwks_client()
        if client is None:
            raise jwt.InvalidTokenError(f"{alg} tokens are not accepted: SUPABASE_URL is unset")
        key = client.get_signing_key_from_jwt(token).key
    else:
        raise jwt.InvalidTokenError(f"unsupported algorithm {alg!r}")

    issuer = f"{settings.supabase_url.rstrip('/')}/auth/v1" if settings.supabase_url else None
    return jwt.decode(
        token,
        key,
        algorithms=[alg],
        audience=settings.jwt_audience,
        issuer=issuer,
        options={"require": ["exp", "sub", "aud"]},
        leeway=30,
    )


class InvalidToken(Exception):
    pass


def user_id_from_token(token: str) -> uuid.UUID:
    """Verify a Supabase JWT and return its user id; raises InvalidToken.

    Shared by the HTTP dependency and the WebSocket handshake. May block on a
    JWKS fetch, so async callers should run it in a thread.
    """
    try:
        claims = decode_supabase_jwt(token)
        # Anon/service-role keys are JWTs too, but have no user `sub`.
        return uuid.UUID(claims["sub"])
    except (jwt.PyJWTError, ValueError, TypeError, KeyError) as exc:
        raise InvalidToken(str(exc)) from exc


# A sync dependency: FastAPI runs it in a threadpool, so the (rare) blocking
# JWKS fetch doesn't stall the event loop.
def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> uuid.UUID:
    """Return the authenticated Supabase user's id from the Bearer token."""
    if credentials is None:
        raise _unauthorized("missing bearer token")
    try:
        return user_id_from_token(credentials.credentials)
    except InvalidToken as exc:
        raise _unauthorized("invalid or expired token") from exc


CurrentUser = Annotated[uuid.UUID, Depends(get_current_user)]
