"""Map route handler — discover links on a page."""

import logging
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Request

from ..exceptions import UpstreamError
from ..link_extractor import extract_links, filter_links
from ..models import MapRequest, MapResponse

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/v2/map", response_model=MapResponse)
async def map_site(request: Request, body: MapRequest) -> MapResponse:
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=15) as client:
            resp = await client.get(body.url)
            if resp.status_code != 200:
                raise UpstreamError(detail=f"Site returned HTTP {resp.status_code}")

            # Use shared LinkExtractor instead of inline BeautifulSoup parsing
            all_links = extract_links(resp.text, body.url)

            # Filter links by domain scope (default: same-origin only)
            base_domain = (urlparse(body.url).hostname or "").lower()
            filtered = filter_links(
                all_links,
                base_domain=base_domain,
                allow_subdomains=body.allow_subdomains,
                allow_external_links=body.allow_external_links,
            )

            # Apply limit (truncates AFTER filtering)
            result = filtered[: body.limit]

            # Apply search filter (case-insensitive substring match)
            if body.search:
                result = [
                    link for link in result if body.search.lower() in link.lower()
                ]

            return MapResponse(links=result)
    except Exception as e:
        logger.error("Map failed for %s: %s", body.url, e)
        raise UpstreamError(detail=str(e)) from e
