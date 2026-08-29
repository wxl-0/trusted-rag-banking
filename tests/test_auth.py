import os
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import Mock, patch

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

os.environ.setdefault("OPENAI_API_KEY", "test-api-key")

with patch("src.generator.answer_builder.AnswerBuilder.__init__", lambda self: None):
    from src.api.main import app

from src.auth import AuthenticationError, Identity, OidcTokenVerifier, get_current_identity


ISSUER = "https://identity.example/realms/trusted-rag"
AUDIENCE = "trusted-rag-api"
KEY_ID = "test-key"


def _identity(role="member"):
    return Identity(
        subject="user-1",
        username="member.demo",
        display_name="演示成员",
        email="member@example.com",
        roles=frozenset({role}),
    )


def _verifier_and_token(*, jwks_url=None, requested_hosts=None, **claim_overrides):
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_jwk = jwt.algorithms.RSAAlgorithm.to_jwk(
        private_key.public_key(), as_dict=True
    )
    public_jwk["kid"] = KEY_ID
    now = int(time.time())
    claims = {
        "sub": "user-1",
        "preferred_username": "member.demo",
        "name": "演示成员",
        "email": "member@example.com",
        "iss": ISSUER,
        "aud": AUDIENCE,
        "iat": now,
        "exp": now + 300,
        "realm_access": {"roles": ["member", "ignored-role"]},
    }
    claims.update(claim_overrides)
    token = jwt.encode(
        claims,
        private_key,
        algorithm="RS256",
        headers={"kid": KEY_ID},
    )

    def handler(request):
        if requested_hosts is not None:
            requested_hosts.append(request.url.host)
        if request.url.path.endswith("openid-configuration"):
            return httpx.Response(200, json={
                "issuer": ISSUER,
                "jwks_uri": f"{ISSUER}/protocol/openid-connect/certs",
            })
        return httpx.Response(200, json={"keys": [public_jwk]})

    verifier = OidcTokenVerifier(
        ISSUER,
        AUDIENCE,
        jwks_url=jwks_url,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    return verifier, token


def test_verifier_accepts_valid_member_and_ignores_unknown_roles():
    verifier, token = _verifier_and_token()

    identity = verifier.verify(token)

    assert identity.subject == "user-1"
    assert identity.roles == frozenset({"member"})
    assert identity.business_role == "member"


def test_verifier_supports_private_backchannel_jwks_url():
    requested_hosts = []
    verifier, token = _verifier_and_token(
        jwks_url="http://keycloak:8080/realms/trusted-rag/certs",
        requested_hosts=requested_hosts,
    )

    identity = verifier.verify(token)

    assert identity.business_role == "member"
    assert requested_hosts == ["identity.example", "keycloak"]


def test_verifier_bypasses_terminal_proxy_for_keycloak_requests():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_jwk = jwt.algorithms.RSAAlgorithm.to_jwk(
        private_key.public_key(), as_dict=True
    )
    public_jwk["kid"] = KEY_ID

    class KeycloakHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path.endswith("openid-configuration"):
                payload = {
                    "issuer": issuer,
                    "jwks_uri": f"{issuer}/protocol/openid-connect/certs",
                }
            else:
                payload = {"keys": [public_jwk]}
            body = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), KeycloakHandler)
    issuer = f"http://127.0.0.1:{server.server_port}/realms/trusted-rag"
    now = int(time.time())
    token = jwt.encode(
        {
            "sub": "user-1",
            "preferred_username": "member.demo",
            "iss": issuer,
            "aud": AUDIENCE,
            "iat": now,
            "exp": now + 300,
            "realm_access": {"roles": ["member"]},
        },
        private_key,
        algorithm="RS256",
        headers={"kid": KEY_ID},
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    proxy_environment = {
        "HTTP_PROXY": "http://127.0.0.1:1",
        "HTTPS_PROXY": "http://127.0.0.1:1",
        "ALL_PROXY": "http://127.0.0.1:1",
        "NO_PROXY": "",
        "http_proxy": "http://127.0.0.1:1",
        "https_proxy": "http://127.0.0.1:1",
        "all_proxy": "http://127.0.0.1:1",
        "no_proxy": "",
    }
    try:
        with patch.dict(os.environ, proxy_environment):
            identity = OidcTokenVerifier(issuer, AUDIENCE).verify(token)
    finally:
        server.shutdown()
        server.server_close()
        thread.join()

    assert identity.business_role == "member"


def test_verifier_rejects_expired_wrong_issuer_and_wrong_audience():
    cases = (
        {"exp": int(time.time()) - 1},
        {"iss": "https://attacker.example/realms/fake"},
        {"aud": "another-api"},
    )
    for overrides in cases:
        verifier, token = _verifier_and_token(**overrides)
        try:
            verifier.verify(token)
        except AuthenticationError:
            continue
        raise AssertionError(f"token should be rejected: {overrides}")


def test_protected_api_requires_login():
    with TestClient(app) as client:
        response = client.post("/api/ask", json={"question": "测试"})

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "AUTH_REQUIRED"


def test_protected_api_rejects_invalid_token_safely():
    verifier = Mock()
    verifier.verify.side_effect = AuthenticationError("raw verifier detail")

    with patch("src.auth.get_token_verifier", return_value=verifier):
        with TestClient(app) as client:
            response = client.post(
                "/api/ask",
                json={"question": "测试"},
                headers={"Authorization": "Bearer invalid-token"},
            )

    assert response.status_code == 401
    assert response.json()["detail"] == {
        "code": "AUTH_INVALID",
        "message": "登录已失效，请重新登录",
    }
    assert "raw verifier detail" not in response.text


def test_identity_api_reports_keycloak_connection_failure_as_unavailable():
    verifier, token = _verifier_and_token()

    def fail_to_connect(request):
        raise httpx.ConnectError("proxy returned 502", request=request)

    verifier.http_client = httpx.Client(
        transport=httpx.MockTransport(fail_to_connect)
    )

    with patch("src.auth.get_token_verifier", return_value=verifier):
        with TestClient(app) as client:
            response = client.get(
                "/api/auth/me",
                headers={"Authorization": f"Bearer {token}"},
            )

    assert response.status_code == 503
    assert response.json()["detail"] == {
        "code": "AUTH_UNAVAILABLE",
        "message": "身份服务暂不可用",
    }
    assert "proxy returned 502" not in response.text


def test_protected_api_rejects_identity_without_business_role():
    verifier = Mock()
    verifier.verify.return_value = _identity(role="unapproved-role")

    with patch("src.auth.get_token_verifier", return_value=verifier):
        with TestClient(app) as client:
            response = client.post(
                "/api/ask",
                json={"question": "测试", "role": "knowledge_maintainer"},
                headers={"Authorization": "Bearer valid-but-unapproved"},
            )

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "ROLE_REQUIRED"


def test_identity_dependency_exposes_only_validated_business_role():
    app.dependency_overrides[get_current_identity] = lambda: _identity("member")
    try:
        with TestClient(app) as client:
            response = client.get("/api/auth/me")
    finally:
        app.dependency_overrides.pop(get_current_identity, None)

    assert response.status_code == 200
    assert response.json()["business_role"] == "member"
    assert response.json()["roles"] == ["member"]


def test_maintainer_inherits_protected_question_access():
    app.dependency_overrides[get_current_identity] = lambda: _identity(
        "knowledge_maintainer"
    )
    result = {
        "answer": "回答",
        "evidence": [],
        "refuse_reason": None,
        "latency_ms": 1,
    }
    try:
        with patch("src.api.routes.builder.answer", return_value=result):
            with TestClient(app) as client:
                response = client.post("/api/ask", json={"question": "测试"})
    finally:
        app.dependency_overrides.pop(get_current_identity, None)

    assert response.status_code == 200
