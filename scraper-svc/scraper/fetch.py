"""Re-exports from fetch_strategy, cache, barrier, and other sub-modules.

This module was split into cache.py, proxy.py, dns_guard.py, barrier.py,
and fetch_strategy.py. This file re-exports all public symbols referenced
by tests, app.py, politeness.py, and recovery.py.
"""

from .barrier import (  # noqa: F401
    BarrierInfo,
    _classify_barrier,
    _is_bot_challenge,
    _is_substack_redirect,
)
from .cache import (  # noqa: F401
    _compute_content_hash,
    _enrich_cache_entry,
    _get_cache_client,
    _merge_cache_metadata,
    _normalize_url_for_cache,
    _parse_domain_ttls,
    _resolve_cache_ttl,
    _scrape_cache_key,
)
from .fetch_strategy import (  # noqa: F401
    QA_MIN_QUALITY_THRESHOLD,
    _quality_acceptable,
    smart_scrape,
)
