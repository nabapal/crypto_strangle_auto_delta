from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import get_settings
from app.main import create_app


@pytest.mark.asyncio
async def test_register_login_and_me_flow(monkeypatch):
    monkeypatch.setenv("BACKEND_LOG_INGEST_ENABLED", "false")
    monkeypatch.setenv("BACKEND_LOG_RETENTION_DAYS", "0")
    get_settings.cache_clear()  # type: ignore[attr-defined]

    app = create_app()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        register_response = await client.post(
            "/api/auth/register",
            json={
                "email": "new.user@example.com",
                "full_name": "New User",
                "password": "strong-pass-1",
            },
        )
        assert register_response.status_code == 201
        user_payload = register_response.json()
        assert user_payload["email"] == "new.user@example.com"
        assert user_payload["is_active"] is True

        login_response = await client.post(
            "/api/auth/login",
            data={"username": "new.user@example.com", "password": "strong-pass-1"},
        )
        assert login_response.status_code == 200
        login_payload = login_response.json()
        token = login_payload["access_token"]
        assert token
        assert login_payload["user"]["email"] == "new.user@example.com"

        me_response = await client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert me_response.status_code == 200
        current_user = me_response.json()
        assert current_user["email"] == "new.user@example.com"


@pytest.mark.asyncio
async def test_protected_endpoint_requires_auth(monkeypatch):
    monkeypatch.setenv("BACKEND_LOG_INGEST_ENABLED", "false")
    monkeypatch.setenv("BACKEND_LOG_RETENTION_DAYS", "0")
    get_settings.cache_clear()  # type: ignore[attr-defined]

    app = create_app()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/api/trading/runtime")

    assert response.status_code == 401
    assert "credentials" in response.text.lower()
