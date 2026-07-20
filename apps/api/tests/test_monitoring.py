from __future__ import annotations

from typing import Any, cast

import pytest
from posthog import Posthog
from starlette.types import Message, Receive, Scope, Send

from app.config import Settings
from app.monitoring import PostHogExceptionMiddleware, build_exception_tracker


class RecordingExceptionTracker:
    def __init__(self) -> None:
        self.calls: list[tuple[BaseException, dict[str, Any]]] = []

    def capture_exception(
        self,
        exception: BaseException,
        **kwargs: Any,
    ) -> str:
        self.calls.append((exception, kwargs))
        return "capture-id"


def test_posthog_is_disabled_without_a_project_key(settings: Settings) -> None:
    assert build_exception_tracker(settings) is None


def test_posthog_sdk_initializes_for_error_tracking(settings: Settings) -> None:
    configured = settings.model_copy(
        update={
            "posthog_api_key": "phc_build_validation",
            "posthog_host": "https://eu.i.posthog.com",
        }
    )

    tracker = build_exception_tracker(configured)

    assert isinstance(tracker, Posthog)
    assert tracker.enable_exception_autocapture is True
    assert tracker.host == "https://eu.i.posthog.com"
    tracker.shutdown()


@pytest.mark.anyio
async def test_unhandled_backend_error_uses_posthog_exception_capture() -> None:
    tracker = RecordingExceptionTracker()
    scope = cast(
        Scope,
        {
            "type": "http",
            "method": "GET",
            "path": "/__monitoring_test_error",
        },
    )

    async def deliberately_fail(
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        del scope, receive, send
        raise RuntimeError("deliberate monitoring validation error")

    async def receive() -> Message:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: Message) -> None:
        del message

    middleware = PostHogExceptionMiddleware(
        deliberately_fail,
        tracker=tracker,
        environment="test",
    )

    with pytest.raises(RuntimeError, match="deliberate monitoring validation error"):
        await middleware(scope, receive, send)

    assert len(tracker.calls) == 1
    exception, kwargs = tracker.calls[0]
    assert isinstance(exception, RuntimeError)
    assert str(exception) == "deliberate monitoring validation error"
    assert kwargs["properties"] == {
        "environment": "test",
        "request_method": "GET",
        "request_path": "/__monitoring_test_error",
    }
