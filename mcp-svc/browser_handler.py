"""Browser session routing — validates sessions and proxies to agent-svc."""

import logging
from typing import Any

from groktocrawl_client import GroktocrawlClient
from session_store import SessionStore

logger = logging.getLogger(__name__)

# Valid browser action types recognised by the GroktoCrawl API.
VALID_ACTIONS: frozenset[str] = frozenset(
    {
        "wait",
        "click",
        "screenshot",
        "scroll",
        "write",
        "executeScript",
        "select",
        "getContent",
        "navigate",
        "type",
    }
)


class BrowserHandler:
    """Routes browser-session operations through the GroktoCrawl API.

    Tracks active sessions in a ``SessionStore`` so that MCP tools can
    validate that a session exists before executing actions.
    """

    def __init__(
        self, client: GroktocrawlClient, session_store: SessionStore
    ) -> None:
        self._client = client
        self._store = session_store

    async def create_session(self, ttl: int = 300) -> dict[str, Any]:
        """Create a new browser session via the API and record it locally.

        Args:
            ttl: Session TTL in seconds (30–3600).

        Returns:
            API response dict — includes ``id`` on success, ``error`` on failure.
        """
        result = await self._client.browser_create(ttl=ttl)
        if "error" not in result:
            session_id = result.get("id")
            if session_id:
                self._store.put(session_id, "browser", ttl)
            else:
                result.setdefault("error", "Browser create: missing id in response")
        return result

    async def execute_action(
        self, session_id: str, action: str, **kwargs: Any
    ) -> dict[str, Any]:
        """Execute a browser action, validating the session exists first.

        Args:
            session_id: The browser session ID returned by ``create_session``.
            action: One of the ``VALID_ACTIONS`` action type strings.
            **kwargs: Action-specific parameters (url, selector, text, etc.).

        Returns:
            API response dict.
        """
        if action not in VALID_ACTIONS:
            return {"error": f"Unknown action type: {action!r}"}

        session = self._store.get(session_id)
        if session is None:
            return {"error": f"Browser session not found: {session_id}"}

        return await self._client.browser_action(
            session_id=session_id, action=action, **kwargs
        )

    async def destroy_session(self, session_id: str) -> dict[str, Any]:
        """Destroy a browser session via the API and remove from local store.

        Args:
            session_id: The browser session ID.

        Returns:
            API response dict.
        """
        result = await self._client.browser_destroy(session_id)
        self._store.delete(session_id)
        return result
