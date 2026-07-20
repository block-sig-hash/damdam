from __future__ import annotations

from typing import Any, Protocol, cast

from posthog import Posthog
from starlette.types import ASGIApp, Receive, Scope, Send

from app.config import Settings


class ExceptionTracker(Protocol):
    def capture_exception(
        self,
        exception: BaseException,
        **kwargs: Any,
    ) -> str | None: ...


def build_exception_tracker(settings: Settings) -> ExceptionTracker | None:
    """Create PostHog only when a project key was supplied at runtime."""
    if not settings.posthog_api_key:
        return None

    return cast(
        ExceptionTracker,
        Posthog(
            project_api_key=settings.posthog_api_key,
            host=settings.posthog_host,
            enable_exception_autocapture=True,
        ),
    )


class PostHogExceptionMiddleware:
    """Send unhandled HTTP exceptions through PostHog's error-tracking API."""

    def __init__(
        self,
        app: ASGIApp,
        tracker: ExceptionTracker,
        environment: str,
    ) -> None:
        self.app = app
        self.tracker = tracker
        self.environment = environment

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        try:
            await self.app(scope, receive, send)
        except Exception as exc:
            self.tracker.capture_exception(
                exc,
                properties={
                    "environment": self.environment,
                    "request_method": scope.get("method", ""),
                    "request_path": scope.get("path", ""),
                },
            )
            raise
