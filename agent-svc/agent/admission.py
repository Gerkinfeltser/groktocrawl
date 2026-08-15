"""Agent-svc admission singleton wiring.

Re-exports the shared :class:`common.admission.AdmissionController` and
exposes a process-wide singleton configured from agent-svc settings. The
singleton is wired onto ``app.state.admission`` so route handlers and the
background worker fan-out share one budget.
"""

from __future__ import annotations

from common.admission import (
    DEFAULT_QUEUE_CAPACITY,
    DEFAULT_WEIGHTS,
    RESOURCE_CLASSES,
    AdmissionController,
    AdmissionRejectedError,
)

from .settings import load_settings

_controller: AdmissionController | None = None


def get_admission() -> AdmissionController:
    """Return the process-wide admission singleton, creating it on demand."""
    global _controller
    if _controller is None:
        settings = load_settings()
        _controller = AdmissionController(
            limits={
                "lightweight_fetch": settings.admission_light_fetch_limit,
                "browser": settings.admission_browser_limit,
                "llm": settings.admission_llm_limit,
            },
        )
    return _controller


def reset_admission() -> None:
    """Drop the cached singleton so the next access rebuilds from settings.

    Primarily a test helper.
    """
    global _controller
    _controller = None


__all__ = [
    "DEFAULT_QUEUE_CAPACITY",
    "DEFAULT_WEIGHTS",
    "RESOURCE_CLASSES",
    "AdmissionController",
    "AdmissionRejectedError",
    "get_admission",
    "reset_admission",
]
