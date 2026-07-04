"""Research planning: LLM-driven plan generation and Valkey-backed plan storage.

Phase 3 of Agent-Native Research milestone: Plan-Consent and Depth Injection.

``ResearchPlanner``  calls the LLM to decompose a user's research prompt into
a structured plan with ordered phases, estimated source counts, and comparison
dimensions.  ``PlanStore`` persists plans in Valkey under the ``plan:`` key
prefix with a 1-hour TTL so the client can review and modify the plan before
executing it.

Plans are one-shot: the first ``consume()`` call (used by the execute endpoint)
deletes the plan from Valkey.  Subsequent attempts to retrieve or execute a
consumed plan return ``None`` (404).
"""

import json
import logging
import uuid
from datetime import UTC, datetime, timedelta

from redis import Redis

from .llm import LLMClient

logger = logging.getLogger(__name__)

# ── Planner system prompt ──────────────────────────────────────

PLAN_SYSTEM_PROMPT = """You are a research planning agent. Your job is to decompose a
user's research prompt into a structured, executable research plan.

RULES:
- Break the research into ordered phases. Each phase must include:
  - ``action``: one of "search" (discover sources via web search),
    "scrape" (fetch specific URLs), or "synthesize" (analyse and
    cross-reference gathered content).
  - ``title``: a short, descriptive label for this phase (max 80 chars).
  - ``description``: detailed explanation of what this phase does and why
    it matters to the overall research goal.
  - ``estimated_sources``: integer — how many distinct web sources this
    specific phase will need.
  - ``queries``: list of 1-5 concrete search queries (for search phases)
    or topic questions (for synthesize phases).  Scrape phases can use
    an empty list or list URLs.
- Estimate the total number of distinct web sources the full research
  will need as ``estimated_sources``.
- Identify comparison or analysis dimensions that should be explored
  (e.g., "cost", "performance", "security", "ecosystem", "community
  support", "learning curve", "scalability").  Return these as
  ``comparison_dimensions``.
- Be specific: tailor every phase to the prompt.  Avoid generic boilerplate.
- If the prompt is broad, include more phases and dimensions.  If narrow,
  keep the plan tight and focused.

Output format — valid JSON only, no other text:

{
  "phases": [
    {
      "action": "search",
      "title": "Initial discovery",
      "description": "Search for the core topic to identify primary sources",
      "estimated_sources": 5,
      "queries": ["query 1", "query 2"]
    },
    {
      "action": "scrape",
      "title": "Deep dive on key sources",
      "description": "Fetch and extract content from the most relevant pages",
      "estimated_sources": 4,
      "queries": []
    },
    {
      "action": "synthesize",
      "title": "Cross-reference and conclude",
      "description": "Analyse findings across all dimensions and produce final answer",
      "estimated_sources": 0,
      "queries": ["What are the key trade-offs?", "How do the options compare?"]
    }
  ],
  "estimated_sources": 9,
  "comparison_dimensions": ["cost", "performance", "ecosystem"]
}

- ``phases``: ordered list of 2-8 phases.  At least one "search" and one
  "synthesize" phase required.  The final phase must be "synthesize".
- ``estimated_sources``: integer — sum of per-phase source counts.
- ``comparison_dimensions``: list of strings — analysis axes to cover."""


class ResearchPlanner:
    """Generates structured research plans by calling the LLM."""

    @staticmethod
    def _normalise_plan(raw_plan: dict, prompt: str) -> dict:
        """Validate and normalise a parsed plan dict from the LLM."""
        phases = raw_plan.get("phases", [])
        if not isinstance(phases, list) or len(phases) == 0:
            raise ValueError("plan.phases must be a non-empty list")

        normalised: list[dict] = []
        for i, phase in enumerate(phases):
            if not isinstance(phase, dict):
                raise ValueError(f"plan.phases[{i}] must be a dict")
            action = phase.get("action", "search")
            if action not in ("search", "scrape", "synthesize"):
                raise ValueError(
                    f"plan.phases[{i}].action must be search/scrape/synthesize, got {action!r}"
                )
            title = phase.get("title", phase.get("description", f"Phase {i + 1}"))
            description = phase.get("description", "")
            estimated = phase.get("estimated_sources", 0)
            queries = phase.get("queries", [])
            if not isinstance(estimated, int) or estimated < 0:
                estimated = 0
            if not isinstance(queries, list):
                queries = []
            normalised.append(
                {
                    "action": action,
                    "title": str(title),
                    "description": str(description),
                    "estimated_sources": estimated,
                    "queries": queries,
                }
            )

        if normalised and normalised[-1].get("action") != "synthesize":
            normalised.append(
                {
                    "action": "synthesize",
                    "title": "Final synthesis",
                    "description": "Final synthesis and cross-referencing of all gathered information",
                    "estimated_sources": 0,
                    "queries": [],
                }
            )

        has_search = any(p.get("action") == "search" for p in normalised)
        if not has_search:
            normalised.insert(
                0,
                {
                    "action": "search",
                    "title": "Initial research",
                    "description": f"Search for: {prompt}",
                    "estimated_sources": 5,
                    "queries": [prompt],
                },
            )

        estimated_sources = raw_plan.get("estimated_sources", 10)
        if not isinstance(estimated_sources, int) or estimated_sources < 1:
            estimated_sources = sum(p.get("estimated_sources", 0) for p in normalised)
            if estimated_sources < 1:
                estimated_sources = len(normalised) * 3

        comparison_dimensions = raw_plan.get(
            "comparison_dimensions",
            raw_plan.get("dimensions", []),
        )
        if not isinstance(comparison_dimensions, list):
            comparison_dimensions = []

        return {
            "phases": normalised,
            "estimated_sources": estimated_sources,
            "comparison_dimensions": comparison_dimensions,
        }

    async def plan(
        self,
        prompt: str,
        llm_client: LLMClient,
        urls: list[str] | None = None,
    ) -> dict:
        """Generate a structured research plan from a user prompt."""
        try:
            user_prompt = prompt
            if urls:
                url_list = "\n".join(f"  - {u}" for u in urls)
                user_prompt = (
                    f"{prompt}\n\n"
                    f"CRITICAL: The following seed URLs have been provided as "
                    f"primary sources.  The plan should treat these as the core "
                    f"information foundation.\n\n"
                    f"Seed URLs:\n{url_list}"
                )
            raw_response = await llm_client.generate(
                system_prompt=PLAN_SYSTEM_PROMPT,
                user_prompt=user_prompt,
            )
            cleaned = raw_response.strip()
            cleaned = cleaned.removeprefix("```json")
            cleaned = cleaned.removeprefix("```")
            cleaned = cleaned.removesuffix("```")
            cleaned = cleaned.strip()
            if not cleaned:
                raise ValueError("Empty response from planning LLM")
            raw_plan = json.loads(cleaned)
            return self._normalise_plan(raw_plan, prompt)
        except Exception as e:
            logger.warning("Plan generation failed, returning fallback plan: %s", e)
            return self._fallback_plan(prompt)

    async def plan_stream(
        self,
        prompt: str,
        llm_client: LLMClient,
        urls: list[str] | None = None,
    ):
        """Generate a research plan with SSE streaming."""
        user_prompt = prompt
        if urls:
            url_list = "\n".join(f"  - {u}" for u in urls)
            user_prompt = (
                f"{prompt}\n\n"
                f"CRITICAL: The following seed URLs have been provided as "
                f"primary sources.\n\nSeed URLs:\n{url_list}"
            )
        accumulated = ""
        try:
            async for chunk in llm_client.generate_stream(
                system_prompt=PLAN_SYSTEM_PROMPT,
                user_prompt=user_prompt,
            ):
                if chunk["type"] == "token":
                    accumulated += chunk["content"]
                    yield ("token", chunk["content"])
                elif chunk["type"] == "error":
                    yield ("error", chunk["content"])
                    return
            cleaned = accumulated.strip()
            cleaned = cleaned.removeprefix("```json")
            cleaned = cleaned.removeprefix("```")
            cleaned = cleaned.removesuffix("```")
            cleaned = cleaned.strip()
            if not cleaned:
                yield ("error", "Empty response from planning LLM")
                plan = self._fallback_plan(prompt)
            else:
                try:
                    raw_plan = json.loads(cleaned)
                    plan = self._normalise_plan(raw_plan, prompt)
                except (json.JSONDecodeError, ValueError) as e:
                    logger.warning("Plan stream parse failed: %s", e)
                    plan = self._fallback_plan(prompt)
            yield ("plan", plan)
        except Exception as e:
            logger.warning("Plan stream failed: %s", e)
            yield ("error", str(e))
            yield ("plan", self._fallback_plan(prompt))

    def _fallback_plan(self, prompt: str) -> dict:
        """Return a safe default plan when LLM generation fails."""
        return {
            "phases": [
                {
                    "action": "search",
                    "title": "Initial research",
                    "description": f"Search for: {prompt}",
                    "estimated_sources": 5,
                    "queries": [prompt],
                },
                {
                    "action": "synthesize",
                    "title": "Synthesis",
                    "description": "Synthesise search results into a comprehensive answer",
                    "estimated_sources": 0,
                    "queries": [],
                },
            ],
            "estimated_sources": 5,
            "comparison_dimensions": [],
        }


class PlanStore:
    """Valkey-backed plan storage with 1-hour TTL and one-shot semantics."""

    def __init__(self, redis_url: str = "redis://localhost:6379/0", ttl: int = 3600):
        self.redis = Redis.from_url(redis_url, decode_responses=True)
        self.ttl = ttl

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(UTC).isoformat()

    @staticmethod
    def _expires_iso(ttl: int = 3600) -> str:
        return (datetime.now(UTC) + timedelta(seconds=ttl)).isoformat()

    def create(self, prompt: str, plan: dict) -> str:
        plan_id = str(uuid.uuid4())
        doc = {
            "plan_id": plan_id,
            "prompt": prompt,
            "plan": plan,
            "created_at": self._now_iso(),
            "expires_at": self._expires_iso(self.ttl),
        }
        self.redis.set(f"plan:{plan_id}", json.dumps(doc), ex=self.ttl)
        logger.info(
            "Plan %s created (%d phases, %d sources estimated)",
            plan_id,
            len(plan.get("phases", [])),
            plan.get("estimated_sources", 0),
        )
        return plan_id

    def get(self, plan_id: str) -> dict | None:
        raw = self.redis.get(f"plan:{plan_id}")
        if raw is None:
            return None
        return json.loads(raw)

    def consume(self, plan_id: str) -> dict | None:
        key = f"plan:{plan_id}"
        pipe = self.redis.pipeline()
        pipe.get(key)
        pipe.delete(key)
        raw_value, _deleted = pipe.execute()
        if raw_value is None:
            return None
        logger.info("Plan %s consumed (one-shot delete)", plan_id)
        return json.loads(raw_value)

    def delete(self, plan_id: str) -> bool:
        deleted = self.redis.delete(f"plan:{plan_id}")
        return deleted > 0
