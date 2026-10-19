"""Structured JSON logging and the observability vocabulary shared by the HTTP and
worker layers.

One JSON object per line on stdout with a stable `service` field. The security
rules about what may reach stdout (HTTP body capture policy, job and usage
events that never carry school content) are stated here, once.
"""

import contextvars
import json
import logging
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import IO, Any

SERVICE_NAME = "mawta-server"  # kept: Loki/Grafana dashboards and runbooks filter on it

# A body larger than this is never captured (never truncated).
MAX_BODY_BYTES = 16 * 1024

CAPTURE_CAPTURED = "captured"
CAPTURE_EMPTY = "empty"
CAPTURE_DISABLED = "disabled"
CAPTURE_OMITTED = "omitted"
CAPTURE_INVALID_JSON = "invalid_json"
CAPTURE_TOO_LARGE = "too_large"

_LEVELS = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warn": logging.WARNING,
    "error": logging.ERROR,
}
_LEVEL_NAMES = {
    logging.DEBUG: "DEBUG",
    logging.INFO: "INFO",
    logging.WARNING: "WARN",
    logging.ERROR: "ERROR",
    logging.CRITICAL: "ERROR",
}


def parse_level(text: str) -> tuple[int, bool]:
    level = _LEVELS.get(text.lower())
    return (level, True) if level is not None else (logging.INFO, False)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "time": datetime.fromtimestamp(record.created, UTC).isoformat().replace("+00:00", "Z"),
            "level": _LEVEL_NAMES.get(record.levelno, "INFO"),
            "msg": record.getMessage(),
            "service": SERVICE_NAME,
        }
        entry.update(getattr(record, "fields", {}))
        return json.dumps(entry, default=str, ensure_ascii=False)


def new_json_logger(level: int, stream: IO[str] | None = None) -> logging.Logger:
    logger = logging.getLogger(SERVICE_NAME)
    logger.handlers.clear()
    handler = logging.StreamHandler(stream or sys.stdout)
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = False
    return logger


def setup(raw_level: str = "") -> logging.Logger:
    raw = raw_level or "info"
    level, ok = parse_level(raw)
    if not ok:
        print(f"WARN invalid LOG_LEVEL {raw!r}, falling back to info", file=sys.stderr)
    return new_json_logger(level)


def log(logger: logging.Logger | None, level: int, msg: str, **fields: Any) -> None:
    if logger is not None:
        logger.log(level, msg, extra={"fields": fields})


def info(logger: logging.Logger | None, msg: str, **fields: Any) -> None:
    log(logger, logging.INFO, msg, **fields)


def warn(logger: logging.Logger | None, msg: str, **fields: Any) -> None:
    log(logger, logging.WARNING, msg, **fields)


def error(logger: logging.Logger | None, msg: str, **fields: Any) -> None:
    log(logger, logging.ERROR, msg, **fields)


_TRUTHY = {"1", "t", "true", "yes", "y", "on"}


def request_body_capture_from_env(value: str) -> bool:
    return value.strip().lower() in _TRUTHY


# --------------------------------------------------------------------------
# HTTP body capture
# --------------------------------------------------------------------------

# Route pattern -> top-level JSON fields that may be logged. Only structural,
# non-free-text fields that carry no student data. A route absent here is never
# captured; the upload route (audio) and auth routes are deliberately absent.
DEFAULT_ALLOWLIST: dict[str, list[str]] = {
    "/api/v1/sessions/{sessionID}/attendance/{studentID}": ["status", "minutes_late"],
    "/api/v1/sessions/{sessionID}/attendance/mark-all-present": [],
    "/api/v1/sessions/{sessionID}/start": [],
    "/api/v1/classes/{classID}/assessments": ["kind", "value_scale", "due_at"],
    "/api/v1/assessments/{assessmentID}/delete": [],
    "/api/v1/criteria/{criterionID}/delete": [],
    "/api/v1/competencies/{competencyID}/capabilities": [],
    "/api/v1/notifications/{notificationID}/read": [],
    "/api/v1/notifications/read-all": [],
    "/api/v1/voice-notes/{voiceNoteID}/save": [],
    "/api/v1/voice-notes/{voiceNoteID}/discard": [],
}

# Never logged at any depth, under any route: the second lock behind the allowlist.
DENIED_FIELDS = frozenset(
    {
        "password", "passwd", "secret", "token", "api_key", "apikey", "key", "authorization",
        "auth", "cookie", "cookies", "session",
        "audio", "input_audio", "data", "transcript", "transcription",
        "student_id", "student", "grade", "grades", "score", "scores", "raw_value", "max_score",
        "level", "value", "note", "notes",
        "title", "description", "body", "text", "name", "username", "code", "q",
    }
)  # fmt: skip


@dataclass(frozen=True)
class CapturedBody:
    status: str
    value: Any = None


def _sanitize_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: None if k in DENIED_FIELDS else _sanitize_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_sanitize_value(v) for v in value]
    if isinstance(value, str):
        # A long string is a smell regardless: drop it rather than ship it.
        return None if len(value) > 200 else value
    return value


def _is_json_content_type(content_type: str) -> bool:
    if not content_type:
        return False
    return content_type.split(";", 1)[0].strip().lower() == "application/json"


@dataclass(frozen=True)
class CapturePolicy:
    enabled: bool
    max_bytes: int = MAX_BODY_BYTES
    allowlist: dict[str, list[str]] = field(default_factory=lambda: DEFAULT_ALLOWLIST)

    def capture_request_body(self, route: str, content_type: str, body: bytes) -> CapturedBody:
        return self._capture(route, content_type, body)

    def capture_response_body(self, route: str, content_type: str, body: bytes) -> CapturedBody:
        # The same allowlist governs both directions.
        return self._capture(route, content_type, body)

    def _capture(self, route: str, content_type: str, body: bytes) -> CapturedBody:
        if not self.enabled:
            return CapturedBody(CAPTURE_DISABLED)
        if not _is_json_content_type(content_type):
            return CapturedBody(CAPTURE_OMITTED)
        if not body:
            return CapturedBody(CAPTURE_EMPTY)
        if self.max_bytes > 0 and len(body) > self.max_bytes:
            return CapturedBody(CAPTURE_TOO_LARGE)
        fields = self.allowlist.get(route)
        if fields is None:
            return CapturedBody(CAPTURE_OMITTED)
        try:
            decoded = json.loads(body)
        except ValueError:
            return CapturedBody(CAPTURE_INVALID_JSON)
        if not isinstance(decoded, dict):
            return CapturedBody(CAPTURE_OMITTED)
        out: dict[str, Any] = {}
        for name in fields:
            if name not in decoded:
                continue
            out[name] = None if name in DENIED_FIELDS else _sanitize_value(decoded[name])
        return CapturedBody(CAPTURE_CAPTURED, out)


def sanitize_error_cause(exc: BaseException | None) -> str:
    """The error's own text, capped; never a body, header or query string."""
    if exc is None:
        return ""
    return str(exc)[:500]


# --------------------------------------------------------------------------
# Worker job events
# --------------------------------------------------------------------------

OUTCOME_SUCCESS = "success"
OUTCOME_RETRYABLE_FAILURE = "retryable_failure"
OUTCOME_PERMANENT_FAILURE = "permanent_failure"
OUTCOME_SKIPPED = "skipped"


def log_job_start(
    logger: logging.Logger | None,
    *,
    task_id: int,
    kind: str,
    attempt: int,
    max_attempts: int,
    worker: str,
) -> None:
    info(
        logger,
        "worker: job started",
        event="worker.job_started",
        task_id=task_id,
        job_id=task_id,
        kind=kind,
        attempt=attempt,
        max_attempts=max_attempts,
        worker=worker,
    )


def log_job_outcome(
    logger: logging.Logger | None,
    *,
    task_id: int,
    kind: str,
    attempt: int,
    max_attempts: int,
    worker: str,
    outcome: str,
    duration_ms: int,
    reason: str = "",
    error_text: str = "",
) -> None:
    fields: dict[str, Any] = {
        "event": "worker.job_outcome",
        "task_id": task_id,
        "job_id": task_id,
        "kind": kind,
        "attempt": attempt,
        "max_attempts": max_attempts,
        "worker": worker,
        "outcome": outcome,
        "duration_ms": duration_ms,
    }
    if reason:
        fields["reason"] = reason
    if error_text:
        fields["error"] = error_text
    level = logging.INFO if outcome in (OUTCOME_SUCCESS, OUTCOME_SKIPPED) else logging.ERROR
    log(logger, level, "worker: job " + outcome, **fields)


# --------------------------------------------------------------------------
# Usage events (never carry prompts, answers, audio or transcripts)
# --------------------------------------------------------------------------

COST_SOURCE_PROVIDER = "provider"
COST_SOURCE_UNKNOWN = "unknown"


def log_agent_usage(
    logger: logging.Logger | None,
    *,
    generation_id: str,
    agent: str,
    kind: str,
    model: str,
    attempt: int,
    duration_ms: int,
    outcome: str,
    error_class: str = "",
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
    cost_usd: float | None = None,
) -> None:
    fields: dict[str, Any] = {
        "event": "agent.usage",
        "generation_id": generation_id,
        "agent": agent,
        "kind": kind,
        "model": model,
        "attempt": attempt,
        "duration_ms": duration_ms,
        "outcome": outcome,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cache_read_tokens": cache_read_tokens,
        "cache_write_tokens": cache_write_tokens,
    }
    if error_class:
        fields["error_class"] = error_class
    if cost_usd is not None:
        fields.update(cost_usd=cost_usd, cost_source="configured_prices")
    else:
        fields.update(cost_usd=None, cost_source=COST_SOURCE_UNKNOWN)
    log(logger, logging.INFO if outcome == "success" else logging.WARNING, "agent usage", **fields)


def log_stt_usage(
    logger: logging.Logger | None,
    *,
    task_id: int,
    attempt: int,
    provider: str,
    model: str,
    duration_ms: int,
    outcome: str,
    generation_id: str = "",
    error_class: str = "",
    cost_usd: float | None = None,
    audio_seconds: float | None = None,
    tokens: int | None = None,
) -> None:
    fields: dict[str, Any] = {
        "event": "stt.usage",
        "task_id": task_id,
        "attempt": attempt,
        "provider": provider,
        "model": model,
        "duration_ms": duration_ms,
        "outcome": outcome,
    }
    if generation_id:
        fields["generation_id"] = generation_id
    if error_class:
        fields["error_class"] = error_class
    if cost_usd is not None:
        fields.update(cost_usd=cost_usd, cost_source=COST_SOURCE_PROVIDER)
    else:
        fields.update(cost_usd=None, cost_source=COST_SOURCE_UNKNOWN)
    if audio_seconds is not None:
        fields["audio_seconds"] = audio_seconds
    if tokens is not None:
        fields["tokens"] = tokens
    log(
        logger,
        logging.INFO if outcome == "success" else logging.WARNING,
        "stt: transcription usage",
        **fields,
    )


# --------------------------------------------------------------------------
# Context carried through a worker attempt
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class STTTask:
    task_id: int
    attempt: int


@dataclass
class OutcomeReport:
    """What a handler says its attempt amounted to when it returns normally."""

    outcome: str = ""
    reason: str = ""


_stt_task: contextvars.ContextVar[STTTask | None] = contextvars.ContextVar("stt_task", default=None)
_outcome_report: contextvars.ContextVar[OutcomeReport | None] = contextvars.ContextVar(
    "outcome_report", default=None
)


def set_stt_task(task: STTTask) -> contextvars.Token:
    return _stt_task.set(task)


def stt_task() -> STTTask | None:
    return _stt_task.get()


def begin_outcome_report() -> tuple[OutcomeReport, contextvars.Token]:
    report = OutcomeReport()
    return report, _outcome_report.set(report)


def end_outcome_report(token: contextvars.Token) -> None:
    _outcome_report.reset(token)


def report_outcome(outcome: str, reason: str) -> None:
    """Record a non-success outcome for the current job attempt (no-op outside a job)."""
    report = _outcome_report.get()
    if report is not None:
        report.outcome, report.reason = outcome, reason
