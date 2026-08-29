import os
from dataclasses import dataclass
from functools import lru_cache

import httpx
import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer


ALLOWED_ROLES = frozenset({"member", "knowledge_maintainer"})
bearer_scheme = HTTPBearer(auto_error=False)


class AuthenticationError(RuntimeError):
    pass


class AuthenticationConfigurationError(RuntimeError):
    pass


class IdentityProviderUnavailableError(RuntimeError):
    pass


@dataclass(frozen=True)
class Identity:
    subject: str
    username: str
    display_name: str
    email: str | None
    roles: frozenset[str]

    @property
    def business_role(self) -> str:
        if "knowledge_maintainer" in self.roles:
            return "knowledge_maintainer"
        if "member" in self.roles:
            return "member"
        raise AuthenticationError("Identity has no approved business role")


class OidcTokenVerifier:
    def __init__(
        self,
        issuer: str,
        audience: str,
        discovery_url: str | None = None,
        jwks_url: str | None = None,
        http_client: httpx.Client | None = None,
    ):
        self.issuer = issuer.rstrip("/")
        self.audience = audience
        self.discovery_url = discovery_url or (
            f"{self.issuer}/.well-known/openid-configuration"
        )
        self.jwks_url = jwks_url
        self.http_client = http_client or httpx.Client(
            timeout=5.0,
            trust_env=False,
        )
        self._jwks_uri: str | None = None
        self._jwks: dict | None = None

    def _load_jwks_uri(self) -> str:
        if self._jwks_uri:
            return self._jwks_uri

        response = self.http_client.get(self.discovery_url)
        response.raise_for_status()
        metadata = response.json()
        if metadata.get("issuer", "").rstrip("/") != self.issuer:
            raise AuthenticationError("OIDC metadata issuer mismatch")
        jwks_uri = metadata.get("jwks_uri")
        if not jwks_uri:
            raise AuthenticationError("OIDC metadata has no jwks_uri")
        self._jwks_uri = self.jwks_url or jwks_uri
        return self._jwks_uri

    def _load_jwks(self, refresh: bool = False) -> dict:
        if self._jwks is not None and not refresh:
            return self._jwks
        response = self.http_client.get(self._load_jwks_uri())
        response.raise_for_status()
        self._jwks = response.json()
        return self._jwks

    def _signing_key(self, key_id: str):
        for refresh in (False, True):
            jwks = self._load_jwks(refresh=refresh)
            for key_data in jwks.get("keys", []):
                if key_data.get("kid") == key_id:
                    return jwt.PyJWK.from_dict(key_data).key
        raise AuthenticationError("No matching OIDC signing key")

    def verify(self, token: str) -> Identity:
        try:
            header = jwt.get_unverified_header(token)
            if header.get("alg") != "RS256" or not header.get("kid"):
                raise AuthenticationError("Unsupported token header")
            claims = jwt.decode(
                token,
                key=self._signing_key(header["kid"]),
                algorithms=["RS256"],
                audience=self.audience,
                issuer=self.issuer,
                options={"require": ["exp", "iat", "sub"]},
            )
        except AuthenticationError:
            raise
        except httpx.HTTPError as exc:
            raise IdentityProviderUnavailableError(
                "OIDC identity provider unavailable"
            ) from exc
        except (jwt.PyJWTError, ValueError, KeyError) as exc:
            raise AuthenticationError("Invalid access token") from exc

        realm_roles = claims.get("realm_access", {}).get("roles", [])
        client_roles = (
            claims.get("resource_access", {})
            .get(self.audience, {})
            .get("roles", [])
        )
        roles = frozenset(realm_roles) | frozenset(client_roles)
        roles = frozenset(role for role in roles if role in ALLOWED_ROLES)
        username = claims.get("preferred_username") or claims["sub"]

        return Identity(
            subject=claims["sub"],
            username=username,
            display_name=claims.get("name") or username,
            email=claims.get("email"),
            roles=roles,
        )


@lru_cache(maxsize=1)
def get_token_verifier() -> OidcTokenVerifier:
    issuer = os.getenv("KEYCLOAK_ISSUER")
    audience = os.getenv("KEYCLOAK_AUDIENCE")
    if not issuer or not audience:
        raise AuthenticationConfigurationError("Keycloak OIDC is not configured")
    return OidcTokenVerifier(
        issuer=issuer,
        audience=audience,
        discovery_url=os.getenv("KEYCLOAK_DISCOVERY_URL"),
        jwks_url=os.getenv("KEYCLOAK_JWKS_URL"),
    )


def _auth_error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"code": code, "message": message},
        headers={"WWW-Authenticate": "Bearer"} if status_code == 401 else None,
    )


def get_current_identity(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> Identity:
    if credentials is None:
        raise _auth_error(401, "AUTH_REQUIRED", "请先登录")

    try:
        identity = get_token_verifier().verify(credentials.credentials)
    except AuthenticationConfigurationError:
        raise _auth_error(503, "AUTH_UNAVAILABLE", "身份服务暂不可用")
    except IdentityProviderUnavailableError:
        raise _auth_error(503, "AUTH_UNAVAILABLE", "身份服务暂不可用")
    except AuthenticationError:
        raise _auth_error(401, "AUTH_INVALID", "登录已失效，请重新登录")

    if not identity.roles.intersection(ALLOWED_ROLES):
        raise _auth_error(403, "ROLE_REQUIRED", "当前账号没有系统访问权限")
    return identity


def require_knowledge_maintainer(
    identity: Identity = Depends(get_current_identity),
) -> Identity:
    if "knowledge_maintainer" not in identity.roles:
        raise _auth_error(
            403,
            "KNOWLEDGE_MAINTAINER_REQUIRED",
            "仅知识库维护者可以管理企业共享知识库",
        )
    return identity
