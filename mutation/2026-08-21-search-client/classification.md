# Mutation Classification — Search-Client Decision Slice (issue #572)

Every in-scope mutant produced by the bounded pilot is classified below. The mutant
set is confined to `agent-svc/agent/searxng_client.py` (VAL-PILOT-001). Classifications
are drawn from the allowed set: killed / survived / equivalent-or-likely-equivalent /
no coverage / timeout / flaky / invalid / infrastructure-tooling failure. The ID set
below exactly matches the raw report's in-scope mutant list (`mutmut-results.txt`);
no mutant is silently omitted.

**In-scope mutants:** 316
**Classified:** 316 / 316

Run directory: `mutation/2026-08-21-search-client`
Raw report: `raw-mutation-report.txt`
Full verdict list: `mutmut-results.txt`
CI/CD stats: `mutmut-cicd-stats.json`
`mutmut show` diffs for all non-killed mutants: `show-diffs/`

| ID | Source path | Operator / Diff | Classification |
|----|-------------|-----------------|----------------|
| `agent.searxng_client.x__parse_retry_after__mutmut_1` | `agent/searxng_client.py` | if not value: -> if value: | killed |
| `agent.searxng_client.x__parse_retry_after__mutmut_2` | `agent/searxng_client.py` | seconds = float(value.strip()) -> seconds = None | killed |
| `agent.searxng_client.x__parse_retry_after__mutmut_3` | `agent/searxng_client.py` | seconds = float(value.strip()) -> seconds = float(None) | killed |
| `agent.searxng_client.x__parse_retry_after__mutmut_4` | `agent/searxng_client.py` | if not math.isfinite(seconds) or seconds < 0: -> if not math.isfinite(seconds) and seconds < 0: | killed |
| `agent.searxng_client.x__parse_retry_after__mutmut_5` | `agent/searxng_client.py` | if not math.isfinite(seconds) or seconds < 0: -> if math.isfinite(seconds) or seconds < 0: | killed |
| `agent.searxng_client.x__parse_retry_after__mutmut_6` | `agent/searxng_client.py` | if not math.isfinite(seconds) or seconds < 0: -> if not math.isfinite(None) or seconds < 0: | killed |
| `agent.searxng_client.x__parse_retry_after__mutmut_7` | `agent/searxng_client.py` | if not math.isfinite(seconds) or seconds < 0: -> if not math.isfinite(seconds) or seconds <= 0: | survived |
| `agent.searxng_client.x__parse_retry_after__mutmut_8` | `agent/searxng_client.py` | if not math.isfinite(seconds) or seconds < 0: -> if not math.isfinite(seconds) or seconds < 1: | survived |
| `agent.searxng_client.xǁSearXNGClientǁ__init____mutmut_1` | `agent/searxng_client.py` | def __init__(self, base_url: str = "http://searxng:8080", max_searches: int = 5): -> def __init__(self, base_url: str = "XXhttp://searxng:8080XX", max_searches: int = 5): | survived |
| `agent.searxng_client.xǁSearXNGClientǁ__init____mutmut_10` | `agent/searxng_client.py` | headers={ -> headers=None, | survived |
| `agent.searxng_client.xǁSearXNGClientǁ__init____mutmut_11` | `agent/searxng_client.py` | timeout=15, | survived |
| `agent.searxng_client.xǁSearXNGClientǁ__init____mutmut_12` | `agent/searxng_client.py` | headers={ -> ) | survived |
| `agent.searxng_client.xǁSearXNGClientǁ__init____mutmut_13` | `agent/searxng_client.py` | timeout=15, -> timeout=16, | survived |
| `agent.searxng_client.xǁSearXNGClientǁ__init____mutmut_14` | `agent/searxng_client.py` | "User-Agent": "GroktoCrawl/0.1", -> "XXUser-AgentXX": "GroktoCrawl/0.1", | survived |
| `agent.searxng_client.xǁSearXNGClientǁ__init____mutmut_15` | `agent/searxng_client.py` | "User-Agent": "GroktoCrawl/0.1", -> "user-agent": "GroktoCrawl/0.1", | survived |
| `agent.searxng_client.xǁSearXNGClientǁ__init____mutmut_16` | `agent/searxng_client.py` | "User-Agent": "GroktoCrawl/0.1", -> "USER-AGENT": "GroktoCrawl/0.1", | survived |
| `agent.searxng_client.xǁSearXNGClientǁ__init____mutmut_17` | `agent/searxng_client.py` | "User-Agent": "GroktoCrawl/0.1", -> "User-Agent": "XXGroktoCrawl/0.1XX", | survived |
| `agent.searxng_client.xǁSearXNGClientǁ__init____mutmut_18` | `agent/searxng_client.py` | "User-Agent": "GroktoCrawl/0.1", -> "User-Agent": "groktocrawl/0.1", | survived |
| `agent.searxng_client.xǁSearXNGClientǁ__init____mutmut_19` | `agent/searxng_client.py` | "User-Agent": "GroktoCrawl/0.1", -> "User-Agent": "GROKTOCRAWL/0.1", | survived |
| `agent.searxng_client.xǁSearXNGClientǁ__init____mutmut_2` | `agent/searxng_client.py` | def __init__(self, base_url: str = "http://searxng:8080", max_searches: int = 5): -> def __init__(self, base_url: str = "HTTP://SEARXNG:8080", max_searches: int = 5): | survived |
| `agent.searxng_client.xǁSearXNGClientǁ__init____mutmut_20` | `agent/searxng_client.py` | "Accept": "text/html,application/json", -> "XXAcceptXX": "text/html,application/json", | survived |
| `agent.searxng_client.xǁSearXNGClientǁ__init____mutmut_21` | `agent/searxng_client.py` | "Accept": "text/html,application/json", -> "accept": "text/html,application/json", | survived |
| `agent.searxng_client.xǁSearXNGClientǁ__init____mutmut_22` | `agent/searxng_client.py` | "Accept": "text/html,application/json", -> "ACCEPT": "text/html,application/json", | survived |
| `agent.searxng_client.xǁSearXNGClientǁ__init____mutmut_23` | `agent/searxng_client.py` | "Accept": "text/html,application/json", -> "Accept": "XXtext/html,application/jsonXX", | survived |
| `agent.searxng_client.xǁSearXNGClientǁ__init____mutmut_24` | `agent/searxng_client.py` | "Accept": "text/html,application/json", -> "Accept": "TEXT/HTML,APPLICATION/JSON", | survived |
| `agent.searxng_client.xǁSearXNGClientǁ__init____mutmut_25` | `agent/searxng_client.py` | "X-Forwarded-For": "127.0.0.1", -> "XXX-Forwarded-ForXX": "127.0.0.1", | survived |
| `agent.searxng_client.xǁSearXNGClientǁ__init____mutmut_26` | `agent/searxng_client.py` | "X-Forwarded-For": "127.0.0.1", -> "x-forwarded-for": "127.0.0.1", | survived |
| `agent.searxng_client.xǁSearXNGClientǁ__init____mutmut_27` | `agent/searxng_client.py` | "X-Forwarded-For": "127.0.0.1", -> "X-FORWARDED-FOR": "127.0.0.1", | survived |
| `agent.searxng_client.xǁSearXNGClientǁ__init____mutmut_28` | `agent/searxng_client.py` | "X-Forwarded-For": "127.0.0.1", -> "X-Forwarded-For": "XX127.0.0.1XX", | survived |
| `agent.searxng_client.xǁSearXNGClientǁ__init____mutmut_29` | `agent/searxng_client.py` | self._search_count = 0 -> self._search_count = None | killed |
| `agent.searxng_client.xǁSearXNGClientǁ__init____mutmut_3` | `agent/searxng_client.py` | def __init__(self, base_url: str = "http://searxng:8080", max_searches: int = 5): -> def __init__(self, base_url: str = "http://searxng:8080", max_searches: int = 6): | survived |
| `agent.searxng_client.xǁSearXNGClientǁ__init____mutmut_30` | `agent/searxng_client.py` | self._search_count = 0 -> self._search_count = 1 | survived |
| `agent.searxng_client.xǁSearXNGClientǁ__init____mutmut_31` | `agent/searxng_client.py` | self._max_searches = max_searches -> self._max_searches = None | killed |
| `agent.searxng_client.xǁSearXNGClientǁ__init____mutmut_4` | `agent/searxng_client.py` | self.base_url = base_url.rstrip("/") -> self.base_url = None | survived |
| `agent.searxng_client.xǁSearXNGClientǁ__init____mutmut_5` | `agent/searxng_client.py` | self.base_url = base_url.rstrip("/") -> self.base_url = base_url.rstrip(None) | survived |
| `agent.searxng_client.xǁSearXNGClientǁ__init____mutmut_6` | `agent/searxng_client.py` | self.base_url = base_url.rstrip("/") -> self.base_url = base_url.lstrip("/") | survived |
| `agent.searxng_client.xǁSearXNGClientǁ__init____mutmut_7` | `agent/searxng_client.py` | self.base_url = base_url.rstrip("/") -> self.base_url = base_url.rstrip("XX/XX") | survived |
| `agent.searxng_client.xǁSearXNGClientǁ__init____mutmut_8` | `agent/searxng_client.py` | self._client = httpx.AsyncClient( -> self._client = None | killed |
| `agent.searxng_client.xǁSearXNGClientǁ__init____mutmut_9` | `agent/searxng_client.py` | timeout=15, -> timeout=None, | survived |
| `agent.searxng_client.xǁSearXNGClientǁ_parse_engine_health__mutmut_1` | `agent/searxng_client.py` | engines = data.get("engines", []) -> engines = None | killed |
| `agent.searxng_client.xǁSearXNGClientǁ_parse_engine_health__mutmut_10` | `agent/searxng_client.py` | engines_responding = sum(1 for e in engines if e.get("results", 0) > 0) -> engines_responding = sum(None) | killed |
| `agent.searxng_client.xǁSearXNGClientǁ_parse_engine_health__mutmut_11` | `agent/searxng_client.py` | engines_responding = sum(1 for e in engines if e.get("results", 0) > 0) -> engines_responding = sum(2 for e in engines if e.get("results", 0) > 0) | killed |
| `agent.searxng_client.xǁSearXNGClientǁ_parse_engine_health__mutmut_12` | `agent/searxng_client.py` | engines_responding = sum(1 for e in engines if e.get("results", 0) > 0) -> engines_responding = sum(1 for e in engines if e.get(None, 0) > 0) | killed |
| `agent.searxng_client.xǁSearXNGClientǁ_parse_engine_health__mutmut_13` | `agent/searxng_client.py` | engines_responding = sum(1 for e in engines if e.get("results", 0) > 0) -> engines_responding = sum(1 for e in engines if e.get("results", None) > 0) | survived |
| `agent.searxng_client.xǁSearXNGClientǁ_parse_engine_health__mutmut_14` | `agent/searxng_client.py` | engines_responding = sum(1 for e in engines if e.get("results", 0) > 0) -> engines_responding = sum(1 for e in engines if e.get(0) > 0) | killed |
| `agent.searxng_client.xǁSearXNGClientǁ_parse_engine_health__mutmut_15` | `agent/searxng_client.py` | engines_responding = sum(1 for e in engines if e.get("results", 0) > 0) -> engines_responding = sum(1 for e in engines if e.get("results", ) > 0) | survived |
| `agent.searxng_client.xǁSearXNGClientǁ_parse_engine_health__mutmut_16` | `agent/searxng_client.py` | engines_responding = sum(1 for e in engines if e.get("results", 0) > 0) -> engines_responding = sum(1 for e in engines if e.get("XXresultsXX", 0) > 0) | killed |
| `agent.searxng_client.xǁSearXNGClientǁ_parse_engine_health__mutmut_17` | `agent/searxng_client.py` | engines_responding = sum(1 for e in engines if e.get("results", 0) > 0) -> engines_responding = sum(1 for e in engines if e.get("RESULTS", 0) > 0) | killed |
| `agent.searxng_client.xǁSearXNGClientǁ_parse_engine_health__mutmut_18` | `agent/searxng_client.py` | engines_responding = sum(1 for e in engines if e.get("results", 0) > 0) -> engines_responding = sum(1 for e in engines if e.get("results", 1) > 0) | survived |
| `agent.searxng_client.xǁSearXNGClientǁ_parse_engine_health__mutmut_19` | `agent/searxng_client.py` | engines_responding = sum(1 for e in engines if e.get("results", 0) > 0) -> engines_responding = sum(1 for e in engines if e.get("results", 0) >= 0) | killed |
| `agent.searxng_client.xǁSearXNGClientǁ_parse_engine_health__mutmut_2` | `agent/searxng_client.py` | engines = data.get("engines", []) -> engines = data.get(None, []) | killed |
| `agent.searxng_client.xǁSearXNGClientǁ_parse_engine_health__mutmut_20` | `agent/searxng_client.py` | engines_responding = sum(1 for e in engines if e.get("results", 0) > 0) -> engines_responding = sum(1 for e in engines if e.get("results", 0) > 1) | killed |
| `agent.searxng_client.xǁSearXNGClientǁ_parse_engine_health__mutmut_21` | `agent/searxng_client.py` | empty_result = bool( -> empty_result = None | killed |
| `agent.searxng_client.xǁSearXNGClientǁ_parse_engine_health__mutmut_22` | `agent/searxng_client.py` | engines_responding > 0 and not any(r.get("url") for r in results) -> None | killed |
| `agent.searxng_client.xǁSearXNGClientǁ_parse_engine_health__mutmut_23` | `agent/searxng_client.py` | engines_responding > 0 and not any(r.get("url") for r in results) -> engines_responding > 0 or not any(r.get("url") for r in results) | killed |
| `agent.searxng_client.xǁSearXNGClientǁ_parse_engine_health__mutmut_24` | `agent/searxng_client.py` | engines_responding > 0 and not any(r.get("url") for r in results) -> engines_responding >= 0 and not any(r.get("url") for r in results) | killed |
| `agent.searxng_client.xǁSearXNGClientǁ_parse_engine_health__mutmut_25` | `agent/searxng_client.py` | engines_responding > 0 and not any(r.get("url") for r in results) -> engines_responding > 1 and not any(r.get("url") for r in results) | killed |
| `agent.searxng_client.xǁSearXNGClientǁ_parse_engine_health__mutmut_26` | `agent/searxng_client.py` | engines_responding > 0 and not any(r.get("url") for r in results) -> engines_responding > 0 and any(r.get("url") for r in results) | killed |
| `agent.searxng_client.xǁSearXNGClientǁ_parse_engine_health__mutmut_27` | `agent/searxng_client.py` | engines_responding > 0 and not any(r.get("url") for r in results) -> engines_responding > 0 and not any(None) | killed |
| `agent.searxng_client.xǁSearXNGClientǁ_parse_engine_health__mutmut_28` | `agent/searxng_client.py` | engines_responding > 0 and not any(r.get("url") for r in results) -> engines_responding > 0 and not any(r.get(None) for r in results) | killed |
| `agent.searxng_client.xǁSearXNGClientǁ_parse_engine_health__mutmut_29` | `agent/searxng_client.py` | engines_responding > 0 and not any(r.get("url") for r in results) -> engines_responding > 0 and not any(r.get("XXurlXX") for r in results) | killed |
| `agent.searxng_client.xǁSearXNGClientǁ_parse_engine_health__mutmut_3` | `agent/searxng_client.py` | engines = data.get("engines", []) -> engines = data.get("engines", None) | survived |
| `agent.searxng_client.xǁSearXNGClientǁ_parse_engine_health__mutmut_30` | `agent/searxng_client.py` | engines_responding > 0 and not any(r.get("url") for r in results) -> engines_responding > 0 and not any(r.get("URL") for r in results) | killed |
| `agent.searxng_client.xǁSearXNGClientǁ_parse_engine_health__mutmut_31` | `agent/searxng_client.py` | degraded = bool(engines_total > 0 and engines_responding < engines_total / 2) -> degraded = None | killed |
| `agent.searxng_client.xǁSearXNGClientǁ_parse_engine_health__mutmut_32` | `agent/searxng_client.py` | degraded = bool(engines_total > 0 and engines_responding < engines_total / 2) -> degraded = bool(None) | killed |
| `agent.searxng_client.xǁSearXNGClientǁ_parse_engine_health__mutmut_33` | `agent/searxng_client.py` | degraded = bool(engines_total > 0 and engines_responding < engines_total / 2) -> degraded = bool(engines_total > 0 or engines_responding < engines_total / 2) | killed |
| `agent.searxng_client.xǁSearXNGClientǁ_parse_engine_health__mutmut_34` | `agent/searxng_client.py` | degraded = bool(engines_total > 0 and engines_responding < engines_total / 2) -> degraded = bool(engines_total >= 0 and engines_responding < engines_total / 2) | survived |
| `agent.searxng_client.xǁSearXNGClientǁ_parse_engine_health__mutmut_35` | `agent/searxng_client.py` | degraded = bool(engines_total > 0 and engines_responding < engines_total / 2) -> degraded = bool(engines_total > 1 and engines_responding < engines_total / 2) | survived |
| `agent.searxng_client.xǁSearXNGClientǁ_parse_engine_health__mutmut_36` | `agent/searxng_client.py` | degraded = bool(engines_total > 0 and engines_responding < engines_total / 2) -> degraded = bool(engines_total > 0 and engines_responding <= engines_total / 2) | survived |
| `agent.searxng_client.xǁSearXNGClientǁ_parse_engine_health__mutmut_37` | `agent/searxng_client.py` | degraded = bool(engines_total > 0 and engines_responding < engines_total / 2) -> degraded = bool(engines_total > 0 and engines_responding < engines_total * 2) | killed |
| `agent.searxng_client.xǁSearXNGClientǁ_parse_engine_health__mutmut_38` | `agent/searxng_client.py` | degraded = bool(engines_total > 0 and engines_responding < engines_total / 2) -> degraded = bool(engines_total > 0 and engines_responding < engines_total / 3) | killed |
| `agent.searxng_client.xǁSearXNGClientǁ_parse_engine_health__mutmut_39` | `agent/searxng_client.py` | if engines_total == 0: -> if engines_total != 0: | killed |
| `agent.searxng_client.xǁSearXNGClientǁ_parse_engine_health__mutmut_4` | `agent/searxng_client.py` | engines = data.get("engines", []) -> engines = data.get([]) | killed |
| `agent.searxng_client.xǁSearXNGClientǁ_parse_engine_health__mutmut_40` | `agent/searxng_client.py` | if engines_total == 0: -> if engines_total == 1: | killed |
| `agent.searxng_client.xǁSearXNGClientǁ_parse_engine_health__mutmut_41` | `agent/searxng_client.py` | detail = "No engine status available from SearXNG" -> detail = None | killed |
| `agent.searxng_client.xǁSearXNGClientǁ_parse_engine_health__mutmut_42` | `agent/searxng_client.py` | detail = "No engine status available from SearXNG" -> detail = "XXNo engine status available from SearXNGXX" | survived |
| `agent.searxng_client.xǁSearXNGClientǁ_parse_engine_health__mutmut_43` | `agent/searxng_client.py` | detail = "No engine status available from SearXNG" -> detail = "no engine status available from searxng" | killed |
| `agent.searxng_client.xǁSearXNGClientǁ_parse_engine_health__mutmut_44` | `agent/searxng_client.py` | detail = "No engine status available from SearXNG" -> detail = "NO ENGINE STATUS AVAILABLE FROM SEARXNG" | killed |
| `agent.searxng_client.xǁSearXNGClientǁ_parse_engine_health__mutmut_45` | `agent/searxng_client.py` | detail = ( -> detail = None | killed |
| `agent.searxng_client.xǁSearXNGClientǁ_parse_engine_health__mutmut_46` | `agent/searxng_client.py` | detail = f"All {engines_total} engines responded but returned no results" -> detail = None | killed |
| `agent.searxng_client.xǁSearXNGClientǁ_parse_engine_health__mutmut_47` | `agent/searxng_client.py` | detail = ( -> detail = None | killed |
| `agent.searxng_client.xǁSearXNGClientǁ_parse_engine_health__mutmut_48` | `agent/searxng_client.py` | engines_total=engines_total, -> engines_total=None, | killed |
| `agent.searxng_client.xǁSearXNGClientǁ_parse_engine_health__mutmut_49` | `agent/searxng_client.py` | engines_responding=engines_responding, -> engines_responding=None, | killed |
| `agent.searxng_client.xǁSearXNGClientǁ_parse_engine_health__mutmut_5` | `agent/searxng_client.py` | engines = data.get("engines", []) -> engines = data.get("engines", ) | survived |
| `agent.searxng_client.xǁSearXNGClientǁ_parse_engine_health__mutmut_50` | `agent/searxng_client.py` | empty_result=empty_result, -> empty_result=None, | killed |
| `agent.searxng_client.xǁSearXNGClientǁ_parse_engine_health__mutmut_51` | `agent/searxng_client.py` | degraded=degraded, -> degraded=None, | killed |
| `agent.searxng_client.xǁSearXNGClientǁ_parse_engine_health__mutmut_52` | `agent/searxng_client.py` | detail=detail, -> detail=None, | killed |
| `agent.searxng_client.xǁSearXNGClientǁ_parse_engine_health__mutmut_53` | `agent/searxng_client.py` | engines_total=engines_total, | killed |
| `agent.searxng_client.xǁSearXNGClientǁ_parse_engine_health__mutmut_54` | `agent/searxng_client.py` | engines_responding=engines_responding, | killed |
| `agent.searxng_client.xǁSearXNGClientǁ_parse_engine_health__mutmut_55` | `agent/searxng_client.py` | empty_result=empty_result, | killed |
| `agent.searxng_client.xǁSearXNGClientǁ_parse_engine_health__mutmut_56` | `agent/searxng_client.py` | degraded=degraded, | killed |
| `agent.searxng_client.xǁSearXNGClientǁ_parse_engine_health__mutmut_57` | `agent/searxng_client.py` | detail=detail, -> ) | killed |
| `agent.searxng_client.xǁSearXNGClientǁ_parse_engine_health__mutmut_6` | `agent/searxng_client.py` | engines = data.get("engines", []) -> engines = data.get("XXenginesXX", []) | killed |
| `agent.searxng_client.xǁSearXNGClientǁ_parse_engine_health__mutmut_7` | `agent/searxng_client.py` | engines = data.get("engines", []) -> engines = data.get("ENGINES", []) | killed |
| `agent.searxng_client.xǁSearXNGClientǁ_parse_engine_health__mutmut_8` | `agent/searxng_client.py` | engines_total = len(engines) -> engines_total = None | killed |
| `agent.searxng_client.xǁSearXNGClientǁ_parse_engine_health__mutmut_9` | `agent/searxng_client.py` | engines_responding = sum(1 for e in engines if e.get("results", 0) > 0) -> engines_responding = None | killed |
| `agent.searxng_client.xǁSearXNGClientǁ_translate__mutmut_1` | `agent/searxng_client.py` | result: list[str] = [] -> result: list[str] = None | killed |
| `agent.searxng_client.xǁSearXNGClientǁ_translate__mutmut_10` | `agent/searxng_client.py` | mapped = _CATEGORIES_MAP.get(c, c) -> mapped = None | killed |
| `agent.searxng_client.xǁSearXNGClientǁ_translate__mutmut_11` | `agent/searxng_client.py` | mapped = _CATEGORIES_MAP.get(c, c) -> mapped = _CATEGORIES_MAP.get(None, c) | killed |
| `agent.searxng_client.xǁSearXNGClientǁ_translate__mutmut_12` | `agent/searxng_client.py` | mapped = _CATEGORIES_MAP.get(c, c) -> mapped = _CATEGORIES_MAP.get(c, None) | survived |
| `agent.searxng_client.xǁSearXNGClientǁ_translate__mutmut_13` | `agent/searxng_client.py` | mapped = _CATEGORIES_MAP.get(c, c) -> mapped = _CATEGORIES_MAP.get(c) | survived |
| `agent.searxng_client.xǁSearXNGClientǁ_translate__mutmut_14` | `agent/searxng_client.py` | mapped = _CATEGORIES_MAP.get(c, c) -> mapped = _CATEGORIES_MAP.get(c, ) | survived |
| `agent.searxng_client.xǁSearXNGClientǁ_translate__mutmut_15` | `agent/searxng_client.py` | if mapped and mapped not in result: -> if mapped or mapped not in result: | killed |
| `agent.searxng_client.xǁSearXNGClientǁ_translate__mutmut_16` | `agent/searxng_client.py` | if mapped and mapped not in result: -> if mapped and mapped in result: | killed |
| `agent.searxng_client.xǁSearXNGClientǁ_translate__mutmut_17` | `agent/searxng_client.py` | result.append(mapped) -> result.append(None) | killed |
| `agent.searxng_client.xǁSearXNGClientǁ_translate__mutmut_18` | `agent/searxng_client.py` | return result or ["general"] -> return result and ["general"] | killed |
| `agent.searxng_client.xǁSearXNGClientǁ_translate__mutmut_19` | `agent/searxng_client.py` | return result or ["general"] -> return result or ["XXgeneralXX"] | killed |
| `agent.searxng_client.xǁSearXNGClientǁ_translate__mutmut_2` | `agent/searxng_client.py` | mapped = _SOURCES_MAP.get(s, s) -> mapped = None | killed |
| `agent.searxng_client.xǁSearXNGClientǁ_translate__mutmut_20` | `agent/searxng_client.py` | return result or ["general"] -> return result or ["GENERAL"] | killed |
| `agent.searxng_client.xǁSearXNGClientǁ_translate__mutmut_3` | `agent/searxng_client.py` | mapped = _SOURCES_MAP.get(s, s) -> mapped = _SOURCES_MAP.get(None, s) | killed |
| `agent.searxng_client.xǁSearXNGClientǁ_translate__mutmut_4` | `agent/searxng_client.py` | mapped = _SOURCES_MAP.get(s, s) -> mapped = _SOURCES_MAP.get(s, None) | killed |
| `agent.searxng_client.xǁSearXNGClientǁ_translate__mutmut_5` | `agent/searxng_client.py` | mapped = _SOURCES_MAP.get(s, s) -> mapped = _SOURCES_MAP.get(s) | killed |
| `agent.searxng_client.xǁSearXNGClientǁ_translate__mutmut_6` | `agent/searxng_client.py` | mapped = _SOURCES_MAP.get(s, s) -> mapped = _SOURCES_MAP.get(s, ) | killed |
| `agent.searxng_client.xǁSearXNGClientǁ_translate__mutmut_7` | `agent/searxng_client.py` | if mapped and mapped not in result: -> if mapped or mapped not in result: | survived |
| `agent.searxng_client.xǁSearXNGClientǁ_translate__mutmut_8` | `agent/searxng_client.py` | if mapped and mapped not in result: -> if mapped and mapped in result: | killed |
| `agent.searxng_client.xǁSearXNGClientǁ_translate__mutmut_9` | `agent/searxng_client.py` | result.append(mapped) -> result.append(None) | killed |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_1` | `agent/searxng_client.py` | limit: int = 10, -> limit: int = 11, | survived |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_10` | `agent/searxng_client.py` | self._search_count += 1 -> self._search_count += 2 | survived |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_100` | `agent/searxng_client.py` | data = resp.json() -> data = None | killed |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_101` | `agent/searxng_client.py` | results = [] -> results = None | killed |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_102` | `agent/searxng_client.py` | for item in data.get("results", []): -> for item in data.get(None, []): | killed |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_103` | `agent/searxng_client.py` | for item in data.get("results", []): -> for item in data.get("results", None): | survived |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_104` | `agent/searxng_client.py` | for item in data.get("results", []): -> for item in data.get([]): | killed |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_105` | `agent/searxng_client.py` | for item in data.get("results", []): -> for item in data.get("results", ): | survived |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_106` | `agent/searxng_client.py` | for item in data.get("results", []): -> for item in data.get("XXresultsXX", []): | killed |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_107` | `agent/searxng_client.py` | for item in data.get("results", []): -> for item in data.get("RESULTS", []): | killed |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_108` | `agent/searxng_client.py` | { -> None | killed |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_109` | `agent/searxng_client.py` | "url": item.get("url", ""), -> "XXurlXX": item.get("url", ""), | killed |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_11` | `agent/searxng_client.py` | effective_categories = self._translate(sources, categories) -> effective_categories = None | killed |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_110` | `agent/searxng_client.py` | "url": item.get("url", ""), -> "URL": item.get("url", ""), | killed |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_111` | `agent/searxng_client.py` | "url": item.get("url", ""), -> "url": item.get(None, ""), | killed |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_112` | `agent/searxng_client.py` | "url": item.get("url", ""), -> "url": item.get("url", None), | survived |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_113` | `agent/searxng_client.py` | "url": item.get("url", ""), -> "url": item.get(""), | killed |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_114` | `agent/searxng_client.py` | "url": item.get("url", ""), -> "url": item.get("url", ), | survived |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_115` | `agent/searxng_client.py` | "url": item.get("url", ""), -> "url": item.get("XXurlXX", ""), | killed |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_116` | `agent/searxng_client.py` | "url": item.get("url", ""), -> "url": item.get("URL", ""), | killed |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_117` | `agent/searxng_client.py` | "url": item.get("url", ""), -> "url": item.get("url", "XXXX"), | survived |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_118` | `agent/searxng_client.py` | "title": item.get("title", ""), -> "XXtitleXX": item.get("title", ""), | survived |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_119` | `agent/searxng_client.py` | "title": item.get("title", ""), -> "TITLE": item.get("title", ""), | survived |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_12` | `agent/searxng_client.py` | effective_categories = self._translate(sources, categories) -> effective_categories = self._translate(None, categories) | survived |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_120` | `agent/searxng_client.py` | "title": item.get("title", ""), -> "title": item.get(None, ""), | survived |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_121` | `agent/searxng_client.py` | "title": item.get("title", ""), -> "title": item.get("title", None), | survived |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_122` | `agent/searxng_client.py` | "title": item.get("title", ""), -> "title": item.get(""), | survived |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_123` | `agent/searxng_client.py` | "title": item.get("title", ""), -> "title": item.get("title", ), | survived |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_124` | `agent/searxng_client.py` | "title": item.get("title", ""), -> "title": item.get("XXtitleXX", ""), | survived |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_125` | `agent/searxng_client.py` | "title": item.get("title", ""), -> "title": item.get("TITLE", ""), | survived |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_126` | `agent/searxng_client.py` | "title": item.get("title", ""), -> "title": item.get("title", "XXXX"), | survived |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_127` | `agent/searxng_client.py` | "description": item.get("content", ""), -> "XXdescriptionXX": item.get("content", ""), | survived |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_128` | `agent/searxng_client.py` | "description": item.get("content", ""), -> "DESCRIPTION": item.get("content", ""), | survived |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_129` | `agent/searxng_client.py` | "description": item.get("content", ""), -> "description": item.get(None, ""), | survived |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_13` | `agent/searxng_client.py` | effective_categories = self._translate(sources, categories) -> effective_categories = self._translate(sources, None) | killed |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_130` | `agent/searxng_client.py` | "description": item.get("content", ""), -> "description": item.get("content", None), | survived |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_131` | `agent/searxng_client.py` | "description": item.get("content", ""), -> "description": item.get(""), | survived |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_132` | `agent/searxng_client.py` | "description": item.get("content", ""), -> "description": item.get("content", ), | survived |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_133` | `agent/searxng_client.py` | "description": item.get("content", ""), -> "description": item.get("XXcontentXX", ""), | survived |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_134` | `agent/searxng_client.py` | "description": item.get("content", ""), -> "description": item.get("CONTENT", ""), | survived |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_135` | `agent/searxng_client.py` | "description": item.get("content", ""), -> "description": item.get("content", "XXXX"), | survived |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_136` | `agent/searxng_client.py` | "engine": item.get("engine", ""), -> "XXengineXX": item.get("engine", ""), | survived |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_137` | `agent/searxng_client.py` | "engine": item.get("engine", ""), -> "ENGINE": item.get("engine", ""), | survived |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_138` | `agent/searxng_client.py` | "engine": item.get("engine", ""), -> "engine": item.get(None, ""), | survived |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_139` | `agent/searxng_client.py` | "engine": item.get("engine", ""), -> "engine": item.get("engine", None), | survived |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_14` | `agent/searxng_client.py` | effective_categories = self._translate(sources, categories) -> effective_categories = self._translate(categories) | killed |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_140` | `agent/searxng_client.py` | "engine": item.get("engine", ""), -> "engine": item.get(""), | survived |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_141` | `agent/searxng_client.py` | "engine": item.get("engine", ""), -> "engine": item.get("engine", ), | survived |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_142` | `agent/searxng_client.py` | "engine": item.get("engine", ""), -> "engine": item.get("XXengineXX", ""), | survived |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_143` | `agent/searxng_client.py` | "engine": item.get("engine", ""), -> "engine": item.get("ENGINE", ""), | survived |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_144` | `agent/searxng_client.py` | "engine": item.get("engine", ""), -> "engine": item.get("engine", "XXXX"), | survived |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_145` | `agent/searxng_client.py` | results = results[:limit] -> results = None | killed |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_146` | `agent/searxng_client.py` | health = self._parse_engine_health(data, results) -> health = None | killed |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_147` | `agent/searxng_client.py` | health = self._parse_engine_health(data, results) -> health = self._parse_engine_health(None, results) | killed |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_148` | `agent/searxng_client.py` | health = self._parse_engine_health(data, results) -> health = self._parse_engine_health(data, None) | killed |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_149` | `agent/searxng_client.py` | health = self._parse_engine_health(data, results) -> health = self._parse_engine_health(results) | killed |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_15` | `agent/searxng_client.py` | effective_categories = self._translate(sources, categories) -> effective_categories = self._translate(sources, ) | killed |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_150` | `agent/searxng_client.py` | health = self._parse_engine_health(data, results) -> health = self._parse_engine_health(data, ) | killed |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_151` | `agent/searxng_client.py` | outcome = "timeout" -> outcome = None | survived |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_152` | `agent/searxng_client.py` | outcome = "timeout" -> outcome = "XXtimeoutXX" | survived |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_153` | `agent/searxng_client.py` | outcome = "timeout" -> outcome = "TIMEOUT" | survived |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_154` | `agent/searxng_client.py` | logger.warning("SearXNG search timed out") -> logger.warning(None) | survived |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_155` | `agent/searxng_client.py` | logger.warning("SearXNG search timed out") -> logger.warning("XXSearXNG search timed outXX") | survived |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_156` | `agent/searxng_client.py` | logger.warning("SearXNG search timed out") -> logger.warning("searxng search timed out") | survived |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_157` | `agent/searxng_client.py` | logger.warning("SearXNG search timed out") -> logger.warning("SEARXNG SEARCH TIMED OUT") | survived |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_158` | `agent/searxng_client.py` | return [], SearchHealth(detail="SearXNG request timed out") -> return [], SearchHealth(detail=None) | killed |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_159` | `agent/searxng_client.py` | return [], SearchHealth(detail="SearXNG request timed out") -> return [], SearchHealth(detail="XXSearXNG request timed outXX") | survived |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_16` | `agent/searxng_client.py` | params = { -> params = None | killed |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_160` | `agent/searxng_client.py` | return [], SearchHealth(detail="SearXNG request timed out") -> return [], SearchHealth(detail="searxng request timed out") | survived |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_161` | `agent/searxng_client.py` | return [], SearchHealth(detail="SearXNG request timed out") -> return [], SearchHealth(detail="SEARXNG REQUEST TIMED OUT") | survived |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_162` | `agent/searxng_client.py` | outcome = "error" -> outcome = None | survived |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_163` | `agent/searxng_client.py` | outcome = "error" -> outcome = "XXerrorXX" | survived |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_164` | `agent/searxng_client.py` | outcome = "error" -> outcome = "ERROR" | survived |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_165` | `agent/searxng_client.py` | logger.error("SearXNG search failed: %s", type(e).__name__) -> logger.error(None, type(e).__name__) | killed |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_166` | `agent/searxng_client.py` | logger.error("SearXNG search failed: %s", type(e).__name__) -> logger.error("SearXNG search failed: %s", None) | survived |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_167` | `agent/searxng_client.py` | logger.error("SearXNG search failed: %s", type(e).__name__) -> logger.error(type(e).__name__) | survived |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_168` | `agent/searxng_client.py` | logger.error("SearXNG search failed: %s", type(e).__name__) -> logger.error("SearXNG search failed: %s", ) | survived |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_169` | `agent/searxng_client.py` | logger.error("SearXNG search failed: %s", type(e).__name__) -> logger.error("XXSearXNG search failed: %sXX", type(e).__name__) | survived |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_17` | `agent/searxng_client.py` | "q": query, -> "XXqXX": query, | survived |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_170` | `agent/searxng_client.py` | logger.error("SearXNG search failed: %s", type(e).__name__) -> logger.error("searxng search failed: %s", type(e).__name__) | survived |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_171` | `agent/searxng_client.py` | logger.error("SearXNG search failed: %s", type(e).__name__) -> logger.error("SEARXNG SEARCH FAILED: %S", type(e).__name__) | killed |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_172` | `agent/searxng_client.py` | logger.error("SearXNG search failed: %s", type(e).__name__) -> logger.error("SearXNG search failed: %s", type(None).__name__) | survived |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_173` | `agent/searxng_client.py` | return [], SearchHealth(detail="SearXNG search failed") -> return [], SearchHealth(detail=None) | killed |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_174` | `agent/searxng_client.py` | return [], SearchHealth(detail="SearXNG search failed") -> return [], SearchHealth(detail="XXSearXNG search failedXX") | survived |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_175` | `agent/searxng_client.py` | return [], SearchHealth(detail="SearXNG search failed") -> return [], SearchHealth(detail="searxng search failed") | survived |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_176` | `agent/searxng_client.py` | return [], SearchHealth(detail="SearXNG search failed") -> return [], SearchHealth(detail="SEARXNG SEARCH FAILED") | survived |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_177` | `agent/searxng_client.py` | _SEARCH_QUERY_SECONDS, -> None, | survived |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_178` | `agent/searxng_client.py` | _SEARCH_QUERY_SECONDS_HELP, -> None, | survived |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_179` | `agent/searxng_client.py` | {"engine": "searxng"}, -> None, | killed |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_18` | `agent/searxng_client.py` | "q": query, -> "Q": query, | survived |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_180` | `agent/searxng_client.py` | started, -> None, | killed |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_181` | `agent/searxng_client.py` | _SEARCH_QUERY_SECONDS, | killed |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_182` | `agent/searxng_client.py` | _SEARCH_QUERY_SECONDS_HELP, | killed |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_183` | `agent/searxng_client.py` | {"engine": "searxng"}, | killed |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_184` | `agent/searxng_client.py` | started, -> ) | killed |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_185` | `agent/searxng_client.py` | {"engine": "searxng"}, -> {"XXengineXX": "searxng"}, | survived |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_186` | `agent/searxng_client.py` | {"engine": "searxng"}, -> {"ENGINE": "searxng"}, | survived |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_187` | `agent/searxng_client.py` | {"engine": "searxng"}, -> {"engine": "XXsearxngXX"}, | survived |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_188` | `agent/searxng_client.py` | {"engine": "searxng"}, -> {"engine": "SEARXNG"}, | survived |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_189` | `agent/searxng_client.py` | _SEARCH_QUERIES_TOTAL, -> None, | survived |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_19` | `agent/searxng_client.py` | "format": "json", -> "XXformatXX": "json", | survived |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_190` | `agent/searxng_client.py` | _SEARCH_QUERIES_TOTAL_HELP, -> None, | survived |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_191` | `agent/searxng_client.py` | {"engine": "searxng", "outcome": outcome}, -> None, | killed |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_192` | `agent/searxng_client.py` | _SEARCH_QUERIES_TOTAL, | killed |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_193` | `agent/searxng_client.py` | _SEARCH_QUERIES_TOTAL_HELP, | killed |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_194` | `agent/searxng_client.py` | {"engine": "searxng", "outcome": outcome}, -> ) | killed |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_195` | `agent/searxng_client.py` | {"engine": "searxng", "outcome": outcome}, -> {"XXengineXX": "searxng", "outcome": outcome}, | survived |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_196` | `agent/searxng_client.py` | {"engine": "searxng", "outcome": outcome}, -> {"ENGINE": "searxng", "outcome": outcome}, | survived |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_197` | `agent/searxng_client.py` | {"engine": "searxng", "outcome": outcome}, -> {"engine": "XXsearxngXX", "outcome": outcome}, | survived |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_198` | `agent/searxng_client.py` | {"engine": "searxng", "outcome": outcome}, -> {"engine": "SEARXNG", "outcome": outcome}, | survived |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_199` | `agent/searxng_client.py` | {"engine": "searxng", "outcome": outcome}, -> {"engine": "searxng", "XXoutcomeXX": outcome}, | survived |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_2` | `agent/searxng_client.py` | raise_on_rate_limit: bool = False, -> raise_on_rate_limit: bool = True, | killed |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_20` | `agent/searxng_client.py` | "format": "json", -> "FORMAT": "json", | survived |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_200` | `agent/searxng_client.py` | {"engine": "searxng", "outcome": outcome}, -> {"engine": "searxng", "OUTCOME": outcome}, | survived |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_21` | `agent/searxng_client.py` | "format": "json", -> "format": "XXjsonXX", | survived |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_22` | `agent/searxng_client.py` | "format": "json", -> "format": "JSON", | survived |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_23` | `agent/searxng_client.py` | "language": "en", -> "XXlanguageXX": "en", | survived |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_24` | `agent/searxng_client.py` | "language": "en", -> "LANGUAGE": "en", | survived |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_25` | `agent/searxng_client.py` | "language": "en", -> "language": "XXenXX", | survived |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_26` | `agent/searxng_client.py` | "language": "en", -> "language": "EN", | survived |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_27` | `agent/searxng_client.py` | "pageno": 1, -> "XXpagenoXX": 1, | survived |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_28` | `agent/searxng_client.py` | "pageno": 1, -> "PAGENO": 1, | survived |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_29` | `agent/searxng_client.py` | "pageno": 1, -> "pageno": 2, | survived |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_3` | `agent/searxng_client.py` | started = time.monotonic() -> started = None | killed |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_30` | `agent/searxng_client.py` | params["categories"] = ",".join(effective_categories) -> params["categories"] = None | killed |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_31` | `agent/searxng_client.py` | params["categories"] = ",".join(effective_categories) -> params["XXcategoriesXX"] = ",".join(effective_categories) | killed |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_32` | `agent/searxng_client.py` | params["categories"] = ",".join(effective_categories) -> params["CATEGORIES"] = ",".join(effective_categories) | killed |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_33` | `agent/searxng_client.py` | params["categories"] = ",".join(effective_categories) -> params["categories"] = ",".join(None) | killed |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_34` | `agent/searxng_client.py` | params["categories"] = ",".join(effective_categories) -> params["categories"] = "XX,XX".join(effective_categories) | killed |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_35` | `agent/searxng_client.py` | run_id = os.getenv("TWIN_RUN_ID") -> run_id = None | survived |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_36` | `agent/searxng_client.py` | run_id = os.getenv("TWIN_RUN_ID") -> run_id = os.getenv(None) | killed |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_37` | `agent/searxng_client.py` | run_id = os.getenv("TWIN_RUN_ID") -> run_id = os.getenv("XXTWIN_RUN_IDXX") | survived |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_38` | `agent/searxng_client.py` | run_id = os.getenv("TWIN_RUN_ID") -> run_id = os.getenv("twin_run_id") | survived |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_39` | `agent/searxng_client.py` | if scenario is not None: -> if scenario is None: | survived |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_4` | `agent/searxng_client.py` | outcome = "success" -> outcome = None | survived |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_40` | `agent/searxng_client.py` | resp = await self._client.get( -> resp = None | killed |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_41` | `agent/searxng_client.py` | f"{self.base_url}/search", -> None, | survived |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_42` | `agent/searxng_client.py` | params=params,  # type: ignore[arg-type] -> params=None,  # type: ignore[arg-type] | killed |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_43` | `agent/searxng_client.py` | f"{self.base_url}/search", | killed |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_44` | `agent/searxng_client.py` | params=params,  # type: ignore[arg-type] -> ) | killed |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_45` | `agent/searxng_client.py` | if resp.status_code == 429: -> if resp.status_code != 429: | killed |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_46` | `agent/searxng_client.py` | if resp.status_code == 429: -> if resp.status_code == 430: | killed |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_47` | `agent/searxng_client.py` | outcome = "rate_limited" -> outcome = None | survived |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_48` | `agent/searxng_client.py` | outcome = "rate_limited" -> outcome = "XXrate_limitedXX" | survived |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_49` | `agent/searxng_client.py` | outcome = "rate_limited" -> outcome = "RATE_LIMITED" | survived |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_5` | `agent/searxng_client.py` | outcome = "success" -> outcome = "XXsuccessXX" | survived |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_50` | `agent/searxng_client.py` | retry_after = _parse_retry_after(resp.headers.get("Retry-After")) -> retry_after = None | killed |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_51` | `agent/searxng_client.py` | retry_after = _parse_retry_after(resp.headers.get("Retry-After")) -> retry_after = _parse_retry_after(None) | killed |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_52` | `agent/searxng_client.py` | retry_after = _parse_retry_after(resp.headers.get("Retry-After")) -> retry_after = _parse_retry_after(resp.headers.get(None)) | killed |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_53` | `agent/searxng_client.py` | retry_after = _parse_retry_after(resp.headers.get("Retry-After")) -> retry_after = _parse_retry_after(resp.headers.get("XXRetry-AfterXX")) | killed |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_54` | `agent/searxng_client.py` | retry_after = _parse_retry_after(resp.headers.get("Retry-After")) -> retry_after = _parse_retry_after(resp.headers.get("retry-after")) | killed |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_55` | `agent/searxng_client.py` | retry_after = _parse_retry_after(resp.headers.get("Retry-After")) -> retry_after = _parse_retry_after(resp.headers.get("RETRY-AFTER")) | killed |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_56` | `agent/searxng_client.py` | "SearXNG rate limited (429) — retry_after=%s", -> None, | killed |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_57` | `agent/searxng_client.py` | retry_after if retry_after is not None else "unknown", -> None, | survived |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_58` | `agent/searxng_client.py` | "SearXNG rate limited (429) — retry_after=%s", | survived |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_59` | `agent/searxng_client.py` | retry_after if retry_after is not None else "unknown", -> ) | survived |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_6` | `agent/searxng_client.py` | outcome = "success" -> outcome = "SUCCESS" | survived |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_60` | `agent/searxng_client.py` | "SearXNG rate limited (429) — retry_after=%s", -> "XXSearXNG rate limited (429) — retry_after=%sXX", | survived |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_61` | `agent/searxng_client.py` | "SearXNG rate limited (429) — retry_after=%s", -> "searxng rate limited (429) — retry_after=%s", | survived |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_62` | `agent/searxng_client.py` | "SearXNG rate limited (429) — retry_after=%s", -> "SEARXNG RATE LIMITED (429) — RETRY_AFTER=%S", | killed |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_63` | `agent/searxng_client.py` | retry_after if retry_after is not None else "unknown", -> retry_after if retry_after is None else "unknown", | survived |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_64` | `agent/searxng_client.py` | retry_after if retry_after is not None else "unknown", -> retry_after if retry_after is not None else "XXunknownXX", | survived |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_65` | `agent/searxng_client.py` | retry_after if retry_after is not None else "unknown", -> retry_after if retry_after is not None else "UNKNOWN", | survived |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_66` | `agent/searxng_client.py` | detail=( -> detail=None, | survived |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_67` | `agent/searxng_client.py` | retry_after_seconds=retry_after, -> retry_after_seconds=None, | killed |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_68` | `agent/searxng_client.py` | detail=( "Downstream search capacity is temporarily exhausted " "(SearXNG returned HTTP 429)" ), | survived |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_69` | `agent/searxng_client.py` | retry_after_seconds=retry_after, -> ) | killed |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_7` | `agent/searxng_client.py` | if self._search_count >= self._max_searches: -> if self._search_count > self._max_searches: | survived |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_70` | `agent/searxng_client.py` | "Downstream search capacity is temporarily exhausted " -> "XXDownstream search capacity is temporarily exhausted XX" | survived |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_71` | `agent/searxng_client.py` | "Downstream search capacity is temporarily exhausted " -> "downstream search capacity is temporarily exhausted " | survived |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_72` | `agent/searxng_client.py` | "Downstream search capacity is temporarily exhausted " -> "DOWNSTREAM SEARCH CAPACITY IS TEMPORARILY EXHAUSTED " | survived |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_73` | `agent/searxng_client.py` | outcome = "degraded" -> outcome = None | survived |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_74` | `agent/searxng_client.py` | outcome = "degraded" -> outcome = "XXdegradedXX" | survived |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_75` | `agent/searxng_client.py` | outcome = "degraded" -> outcome = "DEGRADED" | survived |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_76` | `agent/searxng_client.py` | "SearXNG rate limited (429) — returning empty results " -> None | survived |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_77` | `agent/searxng_client.py` | "SearXNG rate limited (429) — returning empty results " -> "XXSearXNG rate limited (429) — returning empty results XX" | survived |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_78` | `agent/searxng_client.py` | "SearXNG rate limited (429) — returning empty results " -> "searxng rate limited (429) — returning empty results " | survived |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_79` | `agent/searxng_client.py` | "SearXNG rate limited (429) — returning empty results " -> "SEARXNG RATE LIMITED (429) — RETURNING EMPTY RESULTS " | survived |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_8` | `agent/searxng_client.py` | self._search_count += 1 -> self._search_count = 1 | survived |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_80` | `agent/searxng_client.py` | detail="SearXNG returned HTTP 429 (rate limited)" -> detail=None | killed |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_81` | `agent/searxng_client.py` | detail="SearXNG returned HTTP 429 (rate limited)" -> detail="XXSearXNG returned HTTP 429 (rate limited)XX" | survived |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_82` | `agent/searxng_client.py` | detail="SearXNG returned HTTP 429 (rate limited)" -> detail="searxng returned http 429 (rate limited)" | survived |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_83` | `agent/searxng_client.py` | detail="SearXNG returned HTTP 429 (rate limited)" -> detail="SEARXNG RETURNED HTTP 429 (RATE LIMITED)" | survived |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_84` | `agent/searxng_client.py` | if resp.status_code != 200: -> if resp.status_code == 200: | killed |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_85` | `agent/searxng_client.py` | if resp.status_code != 200: -> if resp.status_code != 201: | killed |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_86` | `agent/searxng_client.py` | outcome = "error" -> outcome = None | survived |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_87` | `agent/searxng_client.py` | outcome = "error" -> outcome = "XXerrorXX" | survived |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_88` | `agent/searxng_client.py` | outcome = "error" -> outcome = "ERROR" | survived |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_89` | `agent/searxng_client.py` | "SearXNG returned %d: %s", resp.status_code, resp.text[:200] -> None, resp.status_code, resp.text[:200] | killed |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_9` | `agent/searxng_client.py` | self._search_count += 1 -> self._search_count -= 1 | survived |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_90` | `agent/searxng_client.py` | "SearXNG returned %d: %s", resp.status_code, resp.text[:200] -> "SearXNG returned %d: %s", None, resp.text[:200] | killed |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_91` | `agent/searxng_client.py` | "SearXNG returned %d: %s", resp.status_code, resp.text[:200] -> "SearXNG returned %d: %s", resp.status_code, None | survived |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_92` | `agent/searxng_client.py` | "SearXNG returned %d: %s", resp.status_code, resp.text[:200] -> resp.status_code, resp.text[:200] | killed |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_93` | `agent/searxng_client.py` | "SearXNG returned %d: %s", resp.status_code, resp.text[:200] -> "SearXNG returned %d: %s", resp.text[:200] | killed |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_94` | `agent/searxng_client.py` | "SearXNG returned %d: %s", resp.status_code, resp.text[:200] -> "SearXNG returned %d: %s", resp.status_code, ) | killed |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_95` | `agent/searxng_client.py` | "SearXNG returned %d: %s", resp.status_code, resp.text[:200] -> "XXSearXNG returned %d: %sXX", resp.status_code, resp.text[:200] | survived |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_96` | `agent/searxng_client.py` | "SearXNG returned %d: %s", resp.status_code, resp.text[:200] -> "searxng returned %d: %s", resp.status_code, resp.text[:200] | survived |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_97` | `agent/searxng_client.py` | "SearXNG returned %d: %s", resp.status_code, resp.text[:200] -> "SEARXNG RETURNED %D: %S", resp.status_code, resp.text[:200] | killed |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_98` | `agent/searxng_client.py` | "SearXNG returned %d: %s", resp.status_code, resp.text[:200] -> "SearXNG returned %d: %s", resp.status_code, resp.text[:201] | survived |
| `agent.searxng_client.xǁSearXNGClientǁsearch__mutmut_99` | `agent/searxng_client.py` | detail=f"SearXNG returned HTTP {resp.status_code}" -> detail=None | killed |
