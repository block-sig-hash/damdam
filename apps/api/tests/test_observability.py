"""Redaction, correlation and structured logs — US-42, chunk 26A.

The acceptance criterion is blunt: *verify no tokens, activation codes or
sensitive payloads leak in logs.* So most of this file is adversarial. It logs
the things that must never appear and asserts they do not, including through
paths nobody would write on purpose — an f-string built by a third-party
library, a dict dumped into a message, an exception traceback.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.observability import (
    CORRELATION_HEADER,
    CorrelationIdMiddleware,
    JsonLogFormatter,
    RedactingFilter,
    configure_logging,
    correlation_id,
    redact,
    redact_mapping,
)

#: A syntactically real LPA string with an unusable matching id. It is here to
#: be redacted; it installs nothing.
LPA = "LPA:1$smdp.example.invalid$TESTMATCHINGID0000"
ICCID = "8923410000000012345"


class TestNothingSensitiveSurvives:
    @pytest.mark.parametrize(
        "message",
        [
            f"installing {LPA} for the customer",
            f"iccid={ICCID}",
            "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.payload.signature",
            '{"activation_code": "ABCD-1234-EFGH"}',
            "api_key=sk_live_51H8sample000000000",
            "card 4111111111111111 declined",
            "telnyx_public_key=MCowBQYDK2VwAyEA000000",
            "refresh_token=r0cketfuel",
        ],
    )
    def test_a_secret_shaped_value_never_reaches_the_line(self, message: str) -> None:
        cleaned = redact(message)

        assert "[redacted]" in cleaned
        for secret in (
            "TESTMATCHINGID0000",
            ICCID,
            "eyJhbGciOiJIUzI1NiJ9.payload.signature",
            "ABCD-1234-EFGH",
            "sk_live_51H8sample000000000",
            "4111111111111111",
            "MCowBQYDK2VwAyEA000000",
            "r0cketfuel",
        ):
            assert secret not in cleaned

    def test_the_filter_applies_to_libraries_we_did_not_write(self, caplog) -> None:
        """The whole reason redaction is a filter and not a helper function.

        A helper has to be called. This has to be attached once. A library that
        logs a request body on debug is exactly the code that will never call a
        helper of ours.
        """
        logger = logging.getLogger("some.vendor.sdk")
        logger.addFilter(RedactingFilter())

        with caplog.at_level(logging.INFO, logger="some.vendor.sdk"):
            logger.info("POST /profiles body=%s", {"activation_code": LPA})

        assert LPA not in caplog.text
        assert "TESTMATCHINGID0000" not in caplog.text

    def test_a_traceback_is_redacted_too(self) -> None:
        formatter = JsonLogFormatter()
        try:
            raise ValueError(f"failed to install {LPA}")
        except ValueError:
            record = logging.LogRecord(
                "test", logging.ERROR, __file__, 1, "install failed", (), None
            )
            import sys

            record.exc_info = sys.exc_info()
            rendered = formatter.format(record)

        assert "TESTMATCHINGID0000" not in rendered

    def test_mapping_redaction_is_by_key_and_recursive(self) -> None:
        cleaned = redact_mapping(
            {
                "order_id": "abc",
                "authorization": "Bearer xyz",
                "nested": {"refresh_token": "r0", "safe": "kept"},
            }
        )

        assert cleaned["order_id"] == "abc"
        assert cleaned["authorization"] == "[redacted]"
        assert cleaned["nested"]["refresh_token"] == "[redacted]"
        assert cleaned["nested"]["safe"] == "kept"


class TestStructuredOutput:
    def test_a_record_is_one_json_object_with_its_correlation_id(self) -> None:
        formatter = JsonLogFormatter()
        record = logging.LogRecord(
            "damdam.request", logging.INFO, __file__, 1, "request", (), None
        )
        record.correlation_id = "abc123def456"
        record.route = "/v1/calls/{attempt_id}"
        record.status = 200

        payload = json.loads(formatter.format(record))

        assert payload["correlation_id"] == "abc123def456"
        assert payload["route"] == "/v1/calls/{attempt_id}"
        assert payload["status"] == 200
        assert payload["level"] == "INFO"

    def test_configuring_twice_does_not_double_every_line(self) -> None:
        """A worker that imports the app module twice must not log twice."""
        root = logging.getLogger()
        before = list(root.handlers)
        before_level = root.level
        try:
            configure_logging()
            first = len(root.handlers)
            configure_logging()

            assert len(root.handlers) == first
            assert len([f for f in root.filters if isinstance(f, RedactingFilter)]) == 1
        finally:
            for handler in list(root.handlers):
                if handler not in before:
                    root.removeHandler(handler)
            # `configure_logging` sets the root level, which is correct for a
            # process that calls it once at startup and wrong to leave behind
            # for the rest of a test session.
            root.setLevel(before_level)

    def test_configuring_leaves_somebody_elses_handler_alone(self) -> None:
        """The bug this replaced: it used to remove every root handler.

        Correct in production, where it runs once at startup, and quietly wrong
        everywhere else — under pytest it removed the capture handler and
        blinded log assertions in every test that ran afterwards. A log shipper
        or a supervisor's handler would have gone the same way.
        """
        root = logging.getLogger()
        foreign = logging.NullHandler()
        root.addHandler(foreign)
        try:
            configure_logging()

            assert foreign in root.handlers
        finally:
            root.removeHandler(foreign)
            for handler in list(root.handlers):
                if getattr(handler, "_damdam_observability", False):
                    root.removeHandler(handler)


class _Capture(logging.Handler):
    """Collect records from one named logger, independent of pytest's capture.

    `caplog` attaches to the root logger and depends on global logging state
    surviving every other test in the session. For an assertion about *our
    middleware's own record* that is an unnecessary dependency — and a flaky
    one, since any of a thousand other tests may leave the root logger
    configured differently. Attaching a handler to a logger this test owns
    asserts the same behaviour against the real `LogRecord`.
    """

    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@contextmanager
def _capturing(logger_name: str) -> Iterator[_Capture]:
    logger = logging.getLogger(logger_name)
    handler = _Capture()
    previous_level, previous_propagate = logger.level, logger.propagate
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    # The record must reach *this* handler regardless of what else is attached
    # anywhere above it.
    logger.propagate = False
    try:
        yield handler
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous_level)
        logger.propagate = previous_propagate


def _app(logger_name: str = "damdam.request") -> FastAPI:
    api = FastAPI()
    api.add_middleware(CorrelationIdMiddleware, logger_name=logger_name)

    @api.get("/echo")
    def echo() -> dict[str, str | None]:
        return {"correlation": correlation_id()}

    @api.get("/items/{item_id}")
    def item(item_id: str) -> dict[str, str]:
        return {"item": item_id}

    return api


class TestCorrelation:
    def test_an_id_is_generated_and_echoed_when_the_caller_sends_none(self) -> None:
        response = TestClient(_app()).get("/echo")

        assert response.status_code == 200
        echoed = response.headers[CORRELATION_HEADER]
        # The endpoint saw the same id the response carries, which is the only
        # thing that makes the id worth having.
        assert response.json()["correlation"] == echoed

    def test_a_callers_own_id_is_kept_so_their_logs_join_ours(self) -> None:
        response = TestClient(_app()).get(
            "/echo", headers={CORRELATION_HEADER: "mobile-abc-123"}
        )

        assert response.json()["correlation"] == "mobile-abc-123"

    @pytest.mark.parametrize(
        "hostile",
        ["short", "with space", "inject\r\nSet-Cookie: a=b", "x" * 200, "semi;colon"],
    )
    def test_an_unsafe_caller_id_is_replaced_rather_than_trusted(
        self, hostile: str
    ) -> None:
        """It goes into a response header and into every log line for the request.

        An unvalidated one is a header-injection vector and a way to write
        arbitrary text into our own logs.
        """
        response = TestClient(_app()).get(
            "/echo", headers={CORRELATION_HEADER: hostile}
        )

        echoed = response.headers[CORRELATION_HEADER]
        assert echoed != hostile
        assert "\n" not in echoed and "\r" not in echoed
        assert len(echoed) == 32

    def test_the_request_log_names_the_route_template_not_the_path(self) -> None:
        """Or every customer identifier becomes its own route in log search."""
        name = "damdam.request.route-test"
        with _capturing(name) as captured:
            TestClient(_app(name)).get("/items/cust-9f8e7d")

        records = [
            r for r in captured.records if getattr(r, "event", "") == "http_request"
        ]
        assert records, "the middleware logged nothing"
        assert records[-1].route == "/items/{item_id}"
        # No customer identifier in our own record. `httpx` logs full URLs on
        # its own logger; silencing a third-party logger is a deployment
        # decision, recorded in the handoff rather than asserted here.
        assert "cust-9f8e7d" not in str(records[-1].route)

    def test_a_failing_request_is_still_logged_with_its_status(self) -> None:
        """A request that raises is exactly the one worth having a record of."""
        name = "damdam.request.failure-test"
        api = _app(name)

        @api.get("/boom")
        def boom() -> None:
            raise RuntimeError("nope")

        client = TestClient(api, raise_server_exceptions=False)
        with _capturing(name) as captured:
            client.get("/boom")

        records = [
            r for r in captured.records if getattr(r, "event", "") == "http_request"
        ]
        assert records, "a failing request logged nothing"
        assert records[-1].status == 500
        assert records[-1].correlation_id
