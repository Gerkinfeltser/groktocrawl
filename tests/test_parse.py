"""Tests for parse-svc — document parsing endpoints."""

import io

from fastapi.testclient import TestClient
from parse_svc.app import MAX_SIZE_MB, app

client = TestClient(app)


def test_health():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_metrics():
    resp = client.get("/metrics")
    assert resp.status_code == 200
    assert "text/plain" in resp.headers["content-type"]
    body = resp.text
    assert "# HELP" in body or body.strip() == "# EOF\n"


def test_unsupported_format():
    resp = client.post(
        "/parse",
        files={"file": ("test.xyz", io.BytesIO(b"hello"), "application/octet-stream")},
    )
    assert resp.status_code == 422


def test_file_too_large():
    large_content = b"x" * (MAX_SIZE_MB * 1024 * 1024 + 1)
    resp = client.post(
        "/parse",
        files={"file": ("large.pdf", io.BytesIO(large_content), "application/pdf")},
    )
    assert resp.status_code == 413


def test_pdf_parsing():
    # Minimal valid PDF
    minimal_pdf = (
        b"%PDF-1.4\n"
        b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        b"3 0 obj<</Type/Page/MediaBox[0 0 612 792]/Parent 2 0 R/Resources<<>>>>endobj\n"
        b"xref\n0 4\n0000000000 65535 f \n0000000009 00000 n \n0000000058 00000 n \n0000000115 00000 n \n"
        b"trailer<</Size 4/Root 1 0 R>>\n"
        b"startxref\n190\n%%EOF"
    )
    resp = client.post(
        "/parse",
        files={"file": ("test.pdf", io.BytesIO(minimal_pdf), "application/pdf")},
    )
    assert resp.status_code == 200
    assert resp.json()["success"] is True


def test_txt_parsing():
    resp = client.post(
        "/parse",
        files={"file": ("test.txt", io.BytesIO(b"hello world"), "text/plain")},
    )
    assert resp.status_code == 200
    assert resp.json()["success"] is True
    assert "hello world" in str(resp.json()["data"])


def test_extension_detection():
    resp = client.post(
        "/parse",
        files={
            "file": (
                "report.docx",
                io.BytesIO(b"PK\x03\x04fake"),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )
    assert resp.status_code in (200, 500)
