"""Correlation, structured logs and redaction (US-42, chunk 26A).

An incident is a question about a *request*, not about a line of code. "Why was
this customer charged twice" is answered by following one correlation id across
an API call, a Celery task, a supplier attempt and a webhook — and it is
answerable only if that id exists before anything goes wrong.

Three things live here, and the third is the one that matters most.

**A correlation id per request.** Accepted from the caller when supplied so a
mobile client's own id survives into our logs, generated otherwise, and echoed
back on the response so a support ticket can quote it. Held in a `ContextVar`
so a log call deep inside a service does not need it passed down through six
signatures that have no other reason to know about it.

**Structured records.** One JSON object per line, with the correlation id, the
route, the status and the duration. Greppable by a human, parseable by whatever
the deployment eventually ships logs to, and committed to neither.

**Redaction, applied to the formatted message rather than to the call site.**
This is the important decision. A redaction helper that callers must remember to
use is a redaction helper that is forgotten exactly once, in the one code path
that logs a full activation code. `RedactingFilter` runs over every record this
process emits — including records from libraries we did not write and did not
audit — so the guarantee does not depend on anybody remembering anything.

What it removes: bearer tokens, `Authorization` headers, anything shaped like an
LPA activation string, ICCIDs, long digit runs that could be a card or an
account number, and any value under a key whose name suggests a secret. It is
deliberately aggressive: a redacted log that is slightly harder to read costs an
engineer a minute, and a leaked activation code costs a customer their line.
"""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from collections.abc import Callable, Iterable
from contextvars import ContextVar
from typing import Any

from starlette.types import ASGIApp, Message, Receive, Scope, Send

#: The header a client may supply and that every response carries back.
CORRELATION_HEADER = "x-correlation-id"

_correlation_id: ContextVar[str | None] = ContextVar("correlation_id", default=None)

#: Keys whose *values* never belong in a log, whatever the value looks like.
#:
#: Matched as a **substring, not on word boundaries**: `\b` does not fire
#: between the parts of `refresh_token`, because `_` is a word character, so a
#: boundary-anchored pattern silently misses every snake_case compound key —
#: which is most of the keys in this codebase.
SENSITIVE_KEY_PATTERN = re.compile(
    r"(?i)("
    r"password|passwd|secret|token|authorization|auth|"
    r"activation[_-]?code|lpa|matching[_-]?id|confirmation[_-]?code|"
    r"pin|otp|cvv|credential|signature|refresh|"
    # Any `*key*` except an idempotency key. Redacting those would actively
    # hurt: an idempotency key is the thing an engineer correlates on when
    # investigating a suspected double charge, and it authorizes nothing by
    # itself. Every other kind of key here is either secret or worth hiding.
    r"(?<!idempotency_)key|(?<!idempotency-)key"
    r")"
)

_REDACTED = "[redacted]"

_Replacement = str | Callable[[re.Match[str]], str]

_PATTERNS: tuple[tuple[re.Pattern[str], _Replacement], ...] = (
    # `Bearer <jwt>` and friends, including inside a JSON blob.
    (re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]+"), f"Bearer {_REDACTED}"),
    # An eSIM activation string. `LPA:1$smdp.example.com$MATCHINGID` — the part
    # after the domain is what installs a profile on somebody's phone.
    (re.compile(r"(?i)LPA:[^\s\"',)]+"), _REDACTED),
    # An ICCID: 18-22 digits, usually starting 89. Matched before the generic
    # long-digit rule so the reason is visible in the pattern list.
    (re.compile(r"\b89\d{16,20}\b"), _REDACTED),
    # `"secret_ish_key": "value"` in JSON-ish text. Same substring rule as
    # SENSITIVE_KEY_PATTERN, and for the same snake_case reason.
    (
        re.compile(
            r"(?i)([\"']?[\w-]*(?:password|passwd|secret|token|"
            r"authorization|activation[_-]?code|lpa|matching[_-]?id|pin|otp|cvv|"
            r"credential|signature|(?<!idempotency_)key)[\w-]*[\"']?\s*[:=]\s*)"
            r"([\"']?)([^\s,;}\"']+)\2"
        ),
        lambda match: f"{match.group(1)}{match.group(2)}{_REDACTED}{match.group(2)}",
    ),
    # Any remaining run of 13+ digits. A PAN, an account number, a long token.
    (re.compile(r"\b\d{13,}\b"), _REDACTED),
)


def redact(text: str) -> str:
    """Strip anything that looks like a secret from a formatted log line.

    Order matters: the specific patterns run before the generic long-digit rule
    so that a redacted ICCID is redacted *as an ICCID*, and a reader of this
    module can see which rule caught what.
    """
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def redact_mapping(values: dict[str, Any]) -> dict[str, Any]:
    """Redact by key name, recursively. For structured fields we build ourselves."""
    cleaned: dict[str, Any] = {}
    for key, value in values.items():
        if SENSITIVE_KEY_PATTERN.search(key):
            cleaned[key] = _REDACTED
        elif isinstance(value, dict):
            cleaned[key] = redact_mapping(value)
        elif isinstance(value, str):
            cleaned[key] = redact(value)
        else:
            cleaned[key] = value
    return cleaned


def correlation_id() -> str | None:
    """The current request's id, or `None` outside a request."""
    return _correlation_id.get()


def set_correlation_id(value: str | None) -> None:
    _correlation_id.set(value)


def new_correlation_id() -> str:
    return uuid.uuid4().hex


class RedactingFilter(logging.Filter):
    """Redacts every record, including ones from libraries we did not write.

    A `Filter` rather than a `Formatter` because it must apply no matter which
    handler or formatter a deployment configures. Attached to the root logger,
    it is the last thing between a third-party library's debug line and a log
    aggregator.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # pragma: no cover - a broken record must still pass
            return True
        cleaned = redact(message)
        if cleaned != message:
            # Replace the args too, or a formatter that re-renders them would
            # undo the redaction we just did.
            record.msg = cleaned
            record.args = ()
        return True


class JsonLogFormatter(logging.Formatter):
    """One JSON object per line, carrying the correlation id when there is one."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "level": record.levelname,
            "logger": record.name,
            "message": redact(record.getMessage()),
            "time": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
        }
        correlation = getattr(record, "correlation_id", None) or correlation_id()
        if correlation:
            payload["correlation_id"] = correlation
        for key in ("route", "method", "status", "duration_ms", "event"):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        if record.exc_info:
            payload["exception"] = redact(self.formatException(record.exc_info))
        return json.dumps(payload, ensure_ascii=False, default=str)


#: Marks the handler this module installs, so re-configuring replaces ours and
#: leaves everybody else's alone.
_OURS = "_damdam_observability"


def configure_logging(level: int = logging.INFO, *, json_output: bool = True) -> None:
    """Install the filter and formatter on the root logger.

    Idempotent **without being destructive**, and the distinction matters. An
    earlier version removed every root handler, which made it correct in
    production — where it is called once at startup — and quietly wrong
    everywhere else: it also removed handlers installed by whatever was hosting
    the process. Under pytest that is the capture handler, so calling this in
    one test silently blinded log assertions in every test that ran afterwards.
    Anything that attaches its own handler — a log shipper, a debugger, a
    supervisor — would have lost it the same way.

    So only handlers this function installed are replaced, and the root filter
    is added only once.
    """
    root = logging.getLogger()
    root.setLevel(level)
    for existing in list(root.handlers):
        if getattr(existing, _OURS, False):
            root.removeHandler(existing)
    handler = logging.StreamHandler()
    setattr(handler, _OURS, True)
    handler.setFormatter(
        JsonLogFormatter() if json_output else logging.Formatter("%(message)s")
    )
    handler.addFilter(RedactingFilter())
    root.addHandler(handler)
    # Belt and braces: a handler added later by a library still gets filtered,
    # because the filter is on the logger as well as on our own handler. Added
    # once — a second call must not stack a second filter.
    if not any(isinstance(existing, RedactingFilter) for existing in root.filters):
        root.addFilter(RedactingFilter())


class CorrelationIdMiddleware:
    """Assigns, propagates and echoes the correlation id, and times the request.

    Pure ASGI rather than `BaseHTTPMiddleware`: the latter wraps the request in
    an anonymous task, and a `ContextVar` set inside it is not reliably visible
    to the endpoint. That failure mode is silent — logs simply lose the id under
    load — which is the worst kind.
    """

    def __init__(self, app: ASGIApp, logger_name: str = "damdam.request") -> None:
        self.app = app
        self.logger = logging.getLogger(logger_name)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = _header(scope.get("headers") or [], CORRELATION_HEADER)
        correlation = _clean_correlation(incoming) or new_correlation_id()
        token = _correlation_id.set(correlation)
        started = time.monotonic()
        status_holder = {"status": 500}

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                status_holder["status"] = message["status"]
                headers = list(message.get("headers") or [])
                headers.append(
                    (
                        CORRELATION_HEADER.encode("latin-1"),
                        correlation.encode("latin-1"),
                    )
                )
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            duration_ms = round((time.monotonic() - started) * 1000, 2)
            self.logger.info(
                "request",
                extra={
                    "correlation_id": correlation,
                    # The path template, not the path:
                    # `/v1/calls/{attempt_id}` rather than a line per attempt
                    # id. Raw paths carry customer identifiers into log search
                    # and make every route unique.
                    "route": _route_template(scope),
                    "method": scope.get("method"),
                    "status": status_holder["status"],
                    "duration_ms": duration_ms,
                    "event": "http_request",
                },
            )
            _correlation_id.reset(token)


def _header(headers: Iterable[tuple[bytes, bytes]], name: str) -> str | None:
    wanted = name.lower().encode("latin-1")
    for key, value in headers:
        if key.lower() == wanted:
            return value.decode("latin-1", errors="replace")
    return None


def _clean_correlation(value: str | None) -> str | None:
    """Accept a caller's id only if it is safe to put in a log and a header.

    An id is echoed into a response header and written into every log line for
    the request, so an unvalidated one is both a header-injection vector and a
    way to write arbitrary text into our logs.
    """
    if not value:
        return None
    candidate = value.strip()
    # Rejected outright rather than truncated. Truncating turns a caller's
    # 200-character id into a *different* 64-character id, and then their logs
    # and ours disagree about what the request was called — which is worse than
    # simply issuing our own.
    return candidate if re.fullmatch(r"[A-Za-z0-9._\-]{8,64}", candidate) else None


def _route_template(scope: Scope) -> str | None:
    route = scope.get("route")
    path_format = getattr(route, "path_format", None) or getattr(route, "path", None)
    if isinstance(path_format, str):
        return path_format
    # No route matched (a 404), so there is no template. The raw path would be
    # whatever a scanner asked for, which is not something to index.
    return None
