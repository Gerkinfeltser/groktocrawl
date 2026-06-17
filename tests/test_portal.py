"""Tests for portal-svc — web portal endpoints."""

from fastapi.testclient import TestClient
from portal.app import app

client = TestClient(app)


def test_health():
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["service"] == "portal-svc"


def test_metrics():
    resp = client.get("/metrics")
    assert resp.status_code == 200
    assert "text/plain" in resp.headers["content-type"]
    body = resp.text
    assert "# HELP" in body or body.strip() == "# EOF\n"


def test_index_returns_html():
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "<html" in resp.text.lower()


def test_ask_endpoint_accepts_post():
    resp = client.post("/ask", data={"query": "test", "num_sources": "3"})
    assert resp.status_code in (200, 502, 503)
