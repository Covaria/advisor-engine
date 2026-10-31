"""Who is calling: a verified Supabase access token, or a dev header locally.

Supabase signs access tokens either with the project's asymmetric signing keys
(published at /auth/v1/.well-known/jwks.json) or, on older projects, with a shared
HS256 secret. Both are accepted; the audience must be "authenticated", so anon and
service-role keys are refused. Keep "Confirm email" on in Supabase: it stops a session
being issued before the address is verified, which this server relies on.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

import jwt
from fastapi import Header, HTTPException, Request

from .settings import Settings


@dataclass(frozen=True)
class User:
    id: str
    email: str


@lru_cache(maxsize=4)
def _jwks_client(url: str) -> jwt.PyJWKClient:
    return jwt.PyJWKClient(f"{url}/auth/v1/.well-known/jwks.json", cache_keys=True)


def verify_supabase_token(token: str, settings: Settings) -> User:
    try:
        if settings.supabase_jwt_secret:
            key, algorithms = settings.supabase_jwt_secret, ["HS256"]
        else:
            key = _jwks_client(settings.supabase_url).get_signing_key_from_jwt(token).key
            algorithms = ["ES256", "RS256"]
        claims = jwt.decode(
            token, key, algorithms=algorithms, audience="authenticated",
            issuer=f"{settings.supabase_url}/auth/v1",
            options={"require": ["sub", "exp", "aud", "iss"]},
        )
    except jwt.PyJWTError as e:
        raise HTTPException(401, f"Invalid sign-in token: {e}") from e
    if claims.get("is_anonymous"):
        raise HTTPException(401, "Anonymous sessions cannot use the engine.")
    return User(id=claims["sub"], email=claims.get("email", ""))


def current_user(
    request: Request,
    authorization: str = Header(default=""),
    x_dev_user: str = Header(default=""),
) -> User:
    settings: Settings = request.app.state.settings
    if settings.auth == "dev":
        if not x_dev_user:
            raise HTTPException(401, "Dev auth: send an X-Dev-User header.")
        return User(id=f"dev:{x_dev_user}", email=f"{x_dev_user}@dev.local")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(401, "Sign in required.")
    return verify_supabase_token(token, settings)
