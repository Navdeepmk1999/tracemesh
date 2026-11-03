"""CORS_ORIGINS parsing (app/config.py) and the preflight the frontend sends."""

import pytest

from app.config import Settings

VERCEL = "https://tracemesh.vercel.app"


@pytest.mark.parametrize(
    "raw",
    [
        f'["{VERCEL}"]',  # the documented form
        f' ["{VERCEL}"] ',
        f'["{VERCEL}/"]',  # trailing slash: never matches a browser Origin unless stripped
        f'[" {VERCEL} "]',
        VERCEL,  # a bare origin
        f"{VERCEL}/",
    ],
)
def test_cors_origins_are_normalised(raw, monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", raw)
    assert Settings(_env_file=None).cors_origins == [VERCEL]


def test_cors_origins_accepts_several(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", f"{VERCEL}, http://localhost:3000,")
    assert Settings(_env_file=None).cors_origins == [VERCEL, "http://localhost:3000"]


def test_malformed_json_list_fails_startup(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", f'["{VERCEL}"')
    with pytest.raises(ValueError):
        Settings(_env_file=None)


PREFLIGHT = {
    "Access-Control-Request-Method": "POST",
    "Access-Control-Request-Headers": "authorization,content-type",
}


async def test_preflight_with_bearer_header_is_allowed(client):
    # conftest sets CORS_ORIGINS to ["http://testserver"].
    response = await client.options("/workflows", headers={"Origin": "http://testserver", **PREFLIGHT})
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://testserver"
    assert response.headers["access-control-allow-credentials"] == "true"
    assert "authorization" in response.headers["access-control-allow-headers"].lower()


async def test_preflight_from_unlisted_origin_is_rejected(client):
    response = await client.options("/workflows", headers={"Origin": "https://evil.example", **PREFLIGHT})
    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers
