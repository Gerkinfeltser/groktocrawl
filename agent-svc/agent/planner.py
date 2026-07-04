"""Research planning: LLM-driven plan generation and Valkey-backed plan storage.

Phase 3 of Agent-Native Research milestone: Plan-Consent and Depth Injection.

``ResearchPlanner``  calls the LLM to decompose a user's research prompt into
a structured plan with ordered phases, estimated source counts, and analysis
dimensions.  ``PlanStore`` persists plans in Valkey under the ``plan:`` key
prefix with a 1-hour TTL so the client can review and modify the plan before
executing it.
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
- Break the research into ordered phases. Each phase is one of:
  "search" (discover sources via web search), "scrape" (fetch specific URLs),
  or "synthesize" (analyse and cross-reference gathered content).
- Estimate how many distinct web sources the research will need in total.
- Identify comparison or analysis dimensions that should be explored (e.g.,
  "cost", "performance", "security", "ecosystem", "community support").
- Be specific: tailor every phase to the prompt.  Avoid generic boilerplate.
- If the prompt is broad, include more phases and dimensions.  If narrow, keep
  the plan tight and focused.

Output format — valid JSON only, no other text:

{
  "phases": [
    {
      "action": "search",
      "description": "What to search for and why"
    },
    {
      "action": "scrape",
      "description": "What specific URLs or types of pages to fetch and why"
    },
    {
      "action": "synthesize",
      "description": "What to analyse, compare, or conclude and why"
    }
  ],
  "estimated_sources": 12,
  "dimensions": ["cost", "performance", "ecosystem"]
}

- ``phases``: ordered list of 2-8 phases.  At least one "search" and one
  "synthesize" phase required.  The final phase must be "synthesize".
- ``estimated_sources``: integer — number of distinct web sources expected.
- ``dimensions``: list of strings — comparison or analysis axes to cover."""


class ResearchPlanner:
    """Generates structured research plans by calling the LLM.

    Usage::

        planner = ResearchPlanner()
        llm = LLMClient(base_url, api_key, model)
        plan = await planner.plan(prompt, llm)
        # plan == {"phases": [...], "estimated_sources": 12, "dimensions": [...]}
    """

    async def plan(self, prompt: str, llm_client: LLMClient) -> dict:
        """Generate a structured research plan from a user prompt.

        Args:
            prompt: The user's natural-language research question.
            llm_client: An ``LLMClient`` instance configured with the
                desired model.

        Returns:
            A dict with ``phases`` (list of ``{action, description}``),
            ``estimated_sources`` (int), and ``dimensions`` (list of str).

            On LLM failure or invalid JSON, returns a safe fallback plan
            with a single search and synthesize phase.
        """
        try:
            raw_response = await llm_client.generate(
                system_prompt=PLAN_SYSTEM_PROMPT,
                user_prompt=prompt,
            )

            # Strip markdown code fences if present
            cleaned = raw_response.strip()
            cleaned = cleaned.removeprefix("```json")
            cleaned = cleaned.removeprefix("```")
            cleaned = cleaned.removesuffix("```")
            cleaned = cleaned.strip()

            if not cleaned:
                raise ValueError("Empty response from planning LLM")

            plan = json.loads(cleaned)

            # Validate and normalise
            phases = plan.get("phases", [])
            if not isinstance(phases, list) or len(phases) == 0:
                raise ValueError("plan.phases must be a non-empty list")

            # Ensure every phase has required fields
            for i, phase in enumerate(phases):
                if not isinstance(phase, dict):
                    raise ValueError(f"plan.phases[{i}] must be a dict")
                if "action" not in phase:
                    raise ValueError(f"plan.phases[{i}] missing 'action'")
                if phase["action"] not in ("search", "scrape", "synthesize"):
                    raise ValueError(
                        f"plan.phases[{i}].action must be search/scrape/synthesize, "
                        f"got {phase['action']!r}"
                    )
                if "description" not in phase:
                    phase["description"] = ""

            # Ensure last phase is synthesize
            if phases and phases[-1].get("action") != "synthesize":
                phases.append({"action": "synthesize", "description": "Final synthesis and cross-referencing of all gathered information"})

            estimated_sources = plan.get("estimated_sources", 10)
            if not isinstance(estimated_sources, int) or estimated_sources < 1:
                estimated_sources = 10

            dimensions = plan.get("dimensions", [])
            if not isinstance(dimensions, list):
                dimensions = []

            return {
                "phases": phases,
                "estimated_sources": estimated_sources,
                "dimensions": dimensions,
            }

        except Exception as e:
            logger.warning(
                "Plan generation failed, returning fallback plan: %s", e
            )
            return {
                "phases": [
                    {"action": "search", "description": f"Search for: {prompt}"},
                    {"action": "synthesize", "description": "Synthesise search results into a comprehensive answer"},
                ],
                "estimated_sources": 5,
                "dimensions": [],
            }


class PlanStore:
    """Valkey-backed plan storage with 1-hour TTL.

    Key schema::

        plan:{plan_id}  → JSON {plan_id, prompt, plan, created_at, expires_at}

    All keys carry a 1-hour TTL from creation time.
    """

    def __init__(
        self,
        redis_url: str = "redis://localhost:6379/0",
        ttl: int = 3600,
    ):
        self.redis = Redis.from_url(redis_url, decode_responses=True)
        self.ttl = ttl

    # ── Helpers ─────────────────────────────────────────────────

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(UTC).isoformat()

    @staticmethod
    def _expires_iso(ttl: int = 3600) -> str:
        return (datetime.now(UTC) + timedelta(seconds=ttl)).isoformat()

    # ── CRUD ────────────────────────────────────────────────────

    def create(self, prompt: str, plan: dict) -> str:
        """Persist a research plan and return its ID.

        Args:
            prompt: The original user prompt that generated the plan.
            plan: The plan dict with ``phases``, ``estimated_sources``,
                and ``dimensions``.

        Returns:
            A UUID v4 plan ID string.
        """
        plan_id = str(uuid.uuid4())
        doc = {
            "plan_id": plan_id,
            "prompt": prompt,
            "plan": plan,
            "created_at": self._now_iso(),
            "expires_at": self._expires_iso(self.ttl),
        }
        self.redis.set(
            f"plan:{plan_id}",
            json.dumps(doc),
            ex=self.ttl,
        )
        logger.info("Plan %s created (%d phases, %d sources estimated)",
                     plan_id, len(plan.get("phases", [])), plan.get("estimated_sources", 0))
        return plan_id

    def get(self, plan_id: str) -> dict | None:
        """Retrieve a plan by ID.  Returns ``None`` if not found or expired."""
        raw = self.redis.get(f"plan:{plan_id}")
        if raw is None:
            return None
        return json.loads(raw)

    def delete(self, plan_id: str) -> bool:
        """Delete a plan.  Returns ``True`` if it existed and was deleted."""
        deleted = self.redis.delete(f"plan:{plan_id}")
        return deleted > 0
