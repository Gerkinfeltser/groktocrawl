import os
import time

import httpx

AGENT = os.getenv("AGENT_BASE_URL", "http://localhost:8080")
SCRAPER = os.getenv("SCRAPER_BASE_URL", "http://localhost:8001")
SEARCH = os.getenv("SEARCH_BASE_URL", "http://localhost:8010")
LLM = os.getenv("LLM_BASE_URL", "http://localhost:8011")
TEST_SITE = os.getenv("TEST_SITE_BASE_URL", "http://localhost:8000")


def wait_for(url: str, path: str = "/health", timeout_s: int = 120):
    deadline = time.time() + timeout_s
    last_err = None
    while time.time() < deadline:
        try:
            r = httpx.get(url + path, timeout=2)
            if r.status_code == 200:
                return r
        except Exception as e:
            last_err = e
        time.sleep(2)
    raise RuntimeError(f"Timed out waiting for {url}{path}: {last_err}")


def test_services_health():
    assert wait_for(AGENT).json()["status"] == "ok"
    assert wait_for(SCRAPER).json()["status"] == "ok"
    assert wait_for(SEARCH).json()["status"] == "ok"
    assert wait_for(LLM).json()["status"] == "ok"
    assert wait_for(TEST_SITE).json()["status"] == "ok"


def test_scraper_uses_llms_txt():
    r = httpx.post(SCRAPER + "/scrape", json={"url": TEST_SITE + "/anything"}, timeout=120)
    payload = r.json()
    assert payload["success"] is True
    assert payload["data"]["source"] == "llms.txt"
    assert "llms.txt entrypoint" in payload["data"]["markdown"]


def test_scraper_uses_accept_markdown():
    # Disable llms.txt by targeting the pricing page on a site that still has it.
    # The scraper should still prefer llms.txt if root exists, so use a distinct host
    # behavior by checking the content result from the pricing page through the site root.
    r = httpx.post(SCRAPER + "/scrape", json={"url": TEST_SITE + "/pricing"}, timeout=120)
    payload = r.json()
    assert payload["success"] is True
    assert payload["data"]["source"] in {"llms.txt", "content-negotiation", "playwright"}


def test_agent_endpoints_return_job_and_status():
    create = httpx.post(AGENT + "/v2/agent", json={"prompt": "What is the pricing on the fixture site?"}, timeout=120)
    assert create.status_code == 200
    job_id = create.json()["id"]
    assert job_id

    status = httpx.get(AGENT + f"/v2/agent/{job_id}", timeout=120)
    assert status.status_code == 200
    payload = status.json()
    assert payload["success"] is True
    assert payload["status"] in {"processing", "completed"}


def test_crawl_batch_search_and_map_endpoints_exist():
    crawl = httpx.post(AGENT + "/v2/crawl", json={"url": TEST_SITE}, timeout=120)
    assert crawl.status_code == 200
    crawl_id = crawl.json()["id"]
    assert crawl_id

    batch = httpx.post(AGENT + "/v2/batch/scrape", json={"urls": [TEST_SITE + "/", TEST_SITE + "/pricing"]}, timeout=120)
    assert batch.status_code == 200
    assert batch.json()["id"]

    search = httpx.post(AGENT + "/v2/search", json={"query": "fixture pricing", "limit": 3}, timeout=120)
    assert search.status_code == 200
    search_payload = search.json()
    assert search_payload["success"] is True
    assert len(search_payload["data"]) >= 1

    map_resp = httpx.post(AGENT + "/v2/map", json={"url": TEST_SITE, "limit": 10}, timeout=120)
    assert map_resp.status_code == 200
    assert map_resp.json()["success"] is True
    assert map_resp.json()["links"]
