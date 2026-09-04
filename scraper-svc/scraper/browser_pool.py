"""Bounded, opt-in Playwright browser process reuse.

The pool deliberately keys processes by the domain fingerprint used by
``create_stealth_browser``.  A request always gets a new context, so cookies,
proxy settings, and pages cannot cross request boundaries while the expensive
browser process remains warm.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass
from typing import Any

from .stealth import create_stealth_browser, create_stealth_context, fingerprint_seed

logger = logging.getLogger(__name__)


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float) -> float:
    try:
        return max(0.0, float(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        logger.warning("Invalid %s value; using %s", name, default)
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        logger.warning("Invalid %s value; using %s", name, default)
        return default


@dataclass
class _BrowserEntry:
    browser: Any
    cloakbrowser: bool
    fingerprint: str
    created_at: float
    last_used: float
    leases: int = 0
    contexts: set[Any] | None = None


@dataclass
class BrowserLease:
    """A fresh request context leased from a pooled browser."""

    pool: BrowserPool
    entry: _BrowserEntry
    context: Any
    _released: bool = False

    async def release(self, healthy: bool = True) -> None:
        if self._released:
            return
        self._released = True
        await self.pool.release(self, healthy=healthy)


class BrowserPool:
    """A small lifecycle-managed pool of domain-fingerprinted browsers."""

    def __init__(
        self,
        *,
        enabled: bool = False,
        max_processes: int = 2,
        idle_ttl: float = 60.0,
        max_age: float = 900.0,
    ) -> None:
        self.enabled = enabled
        self.max_processes = max(1, int(max_processes))
        self.idle_ttl = max(0.0, float(idle_ttl))
        self.max_age = max(0.0, float(max_age))
        self._condition = asyncio.Condition()
        self._entries: list[_BrowserEntry] = []
        self._launching = 0
        self._playwright_manager: Any = None
        self._playwright: Any = None
        self._reaper_task: asyncio.Task[None] | None = None
        self._started = False
        self._closing = False

    @classmethod
    def from_env(cls) -> BrowserPool:
        return cls(
            enabled=_env_bool("SCRAPER_BROWSER_POOL_ENABLED"),
            max_processes=_env_int("SCRAPER_BROWSER_POOL_MAX_PROCESSES", 2),
            idle_ttl=_env_float("SCRAPER_BROWSER_POOL_IDLE_TTL_SECONDS", 60.0),
            max_age=_env_float("SCRAPER_BROWSER_POOL_MAX_AGE_SECONDS", 900.0),
        )

    @property
    def process_count(self) -> int:
        return len(self._entries)

    async def start(self) -> None:
        """Start one shared Playwright controller, if pooling is enabled."""
        if not self.enabled or self._started:
            return
        async with self._condition:
            if self._started:
                return
            if self._closing:
                raise RuntimeError("browser pool is closed")
            from playwright.async_api import async_playwright

            manager = async_playwright()
            try:
                playwright = await manager.__aenter__()
            except BaseException:
                await manager.__aexit__(None, None, None)
                raise
            self._playwright_manager = manager
            self._playwright = playwright
            self._started = True
            self._reaper_task = asyncio.create_task(
                self._reap_loop(), name="scraper-browser-pool-reaper"
            )
        logger.info(
            "Browser pool started (max_processes=%d idle_ttl=%.1fs max_age=%.1fs)",
            self.max_processes,
            self.idle_ttl,
            self.max_age,
        )

    async def acquire(self, url: str, proxy: dict | None = None) -> BrowserLease:
        """Lease a fresh context, waiting while the process bound is full."""
        if not self.enabled:
            raise RuntimeError("browser pool is disabled")
        await self.start()
        fingerprint = fingerprint_seed(url)

        while True:
            await self._reap_expired()
            retire: _BrowserEntry | None = None
            async with self._condition:
                if self._closing:
                    raise RuntimeError("browser pool is closed")
                entry = next(
                    (item for item in self._entries if item.fingerprint == fingerprint),
                    None,
                )
                if entry is not None:
                    entry.leases += 1
                    break
                if len(self._entries) + self._launching < self.max_processes:
                    self._launching += 1
                    break
                # A different-domain request cannot use an idle process with
                # the wrong fingerprint. Recycle one immediately so the
                # bounded pool does not wait forever for its own capacity.
                retire = next(
                    (item for item in self._entries if item.leases == 0), None
                )
                if retire is None:
                    await self._condition.wait()
                else:
                    self._entries.remove(retire)
                    self._condition.notify_all()

            # The condition is notified by release/recycle. Re-check expiry and
            # availability in the next iteration rather than holding the lock.
            if retire is not None:
                try:
                    await retire.browser.close()
                except Exception:
                    logger.debug("Recycled browser cleanup failed", exc_info=True)

        if entry is None:
            try:
                browser, cloakbrowser = await create_stealth_browser(
                    self._playwright, url
                )
                now = time.monotonic()
                entry = _BrowserEntry(
                    browser=browser,
                    cloakbrowser=cloakbrowser,
                    fingerprint=fingerprint,
                    created_at=now,
                    last_used=now,
                    leases=1,
                    contexts=set(),
                )
                async with self._condition:
                    self._launching -= 1
                    if self._closing:
                        self._condition.notify_all()
                    else:
                        self._entries.append(entry)
                        self._condition.notify_all()
            except BaseException:
                async with self._condition:
                    self._launching -= 1
                    self._condition.notify_all()
                raise

        try:
            context_kwargs = {"proxy": proxy} if proxy else {}
            context = await create_stealth_context(
                entry.browser,
                cloakbrowser=entry.cloakbrowser,
                **context_kwargs,
            )
            async with self._condition:
                recycled = entry not in self._entries
                if not recycled:
                    if entry.contexts is None:
                        entry.contexts = set()
                    entry.contexts.add(context)
            if recycled:
                await context.close()
                raise RuntimeError("browser process was recycled during setup")
            return BrowserLease(self, entry, context)
        except BaseException:
            await self._discard(entry)
            raise

    async def release(self, lease: BrowserLease, *, healthy: bool = True) -> None:
        """Close the request context and return or recycle its browser."""

        async def cleanup() -> None:
            try:
                await lease.context.close()
            except Exception:
                healthy_local = False
                logger.debug("Browser context cleanup failed", exc_info=True)
            else:
                healthy_local = healthy
            async with self._condition:
                if lease.entry.contexts is not None:
                    lease.entry.contexts.discard(lease.context)
            if not healthy_local:
                await self._discard(lease.entry)
                return
            async with self._condition:
                if lease.entry in self._entries:
                    lease.entry.leases = max(0, lease.entry.leases - 1)
                    lease.entry.last_used = time.monotonic()
                    self._condition.notify_all()

        task = asyncio.create_task(cleanup(), name="scraper-browser-context-cleanup")
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            # Let the cleanup task finish after request cancellation. Browser
            # processes are otherwise left busy until the next acquisition.
            task.add_done_callback(lambda done: done.exception())
            raise

    async def _discard(self, entry: _BrowserEntry) -> None:
        async with self._condition:
            if entry not in self._entries:
                entry.leases = 0
            else:
                self._entries.remove(entry)
                entry.leases = 0
            contexts = list(entry.contexts or ())
            if entry.contexts is not None:
                entry.contexts.clear()
            self._condition.notify_all()
        for context in contexts:
            try:
                await context.close()
            except Exception:
                logger.debug("Browser context cleanup failed", exc_info=True)
        try:
            await entry.browser.close()
        except Exception:
            logger.debug("Browser process cleanup failed", exc_info=True)

    async def _reap_expired(self) -> None:
        now = time.monotonic()
        async with self._condition:
            expired = [
                entry
                for entry in self._entries
                if entry.leases == 0
                and (
                    now - entry.last_used >= self.idle_ttl
                    or now - entry.created_at >= self.max_age
                )
            ]
            for entry in expired:
                self._entries.remove(entry)
            if expired:
                self._condition.notify_all()
        for entry in expired:
            try:
                await entry.browser.close()
            except Exception:
                logger.debug("Expired browser cleanup failed", exc_info=True)

    async def _reap_loop(self) -> None:
        interval = max(0.1, min(self.idle_ttl or 0.1, 30.0))
        try:
            while True:
                await asyncio.sleep(interval)
                await self._reap_expired()
        except asyncio.CancelledError:
            return

    async def close(self) -> None:
        """Close all processes and the shared Playwright controller."""
        if not self._started and not self._entries:
            self._closing = True
            return
        async with self._condition:
            self._closing = True
            entries = list(self._entries)
            self._entries.clear()
            self._condition.notify_all()
            reaper = self._reaper_task
            manager = self._playwright_manager
            self._reaper_task = None
            self._playwright_manager = None
            self._playwright = None
            self._started = False
        if reaper is not None:
            reaper.cancel()
            await asyncio.gather(reaper, return_exceptions=True)
        for entry in entries:
            for context in list(entry.contexts or ()):
                try:
                    await context.close()
                except Exception:
                    logger.debug("Browser context shutdown failed", exc_info=True)
            try:
                await entry.browser.close()
            except Exception:
                logger.debug("Browser process shutdown failed", exc_info=True)
        if manager is not None:
            try:
                await manager.__aexit__(None, None, None)
            except Exception:
                logger.debug("Playwright controller shutdown failed", exc_info=True)


_browser_pool = BrowserPool.from_env()


def get_browser_pool() -> BrowserPool:
    return _browser_pool


async def close_browser_pool() -> None:
    await _browser_pool.close()
