"""Continuous-improvement review of the director chat: reads chat.question_bank, chat.messages
and chat.message_feedback over a window of days and turns them into an actionable report (missing
tools backlog, negative feedback with trace ids, recurring partial answers, and draft cases for
src/chat/eval/bank.py)."""

import json
import re
import unicodedata
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncConnection

from mawta_schema.tables import ChatMessage, ChatMessageFeedback, ChatQuestionBank


@dataclass(frozen=True)
class MissingToolTopic:
    topic: str
    count: int
    samples: list[str]


@dataclass(frozen=True)
class NegativeFeedbackItem:
    message_id: str
    question: str
    reason: str | None
    comment: str | None
    tools: list[str]
    trace_id: str | None
    created_at: str


@dataclass(frozen=True)
class PartialQuestionItem:
    question: str
    tool_name: str | None
    created_at: str


@dataclass
class ReviewReport:
    days: int
    totals: dict[str, int] = field(default_factory=dict)
    missing_tools: list[MissingToolTopic] = field(default_factory=list)
    negative_feedback: list[NegativeFeedbackItem] = field(default_factory=list)
    partial_questions: list[PartialQuestionItem] = field(default_factory=list)


def _slug(text: str) -> str:
    stripped = "".join(
        ch for ch in unicodedata.normalize("NFKD", text) if not unicodedata.combining(ch)
    )
    words = re.findall(r"[a-z0-9]+", stripped.lower())
    return "-".join(words[:5]) or "caso"


def _question_text(blocks: Any) -> str:
    if isinstance(blocks, list):
        for block in blocks:
            if isinstance(block, dict) and block.get("tipo") == "texto":
                md = block.get("md")
                if isinstance(md, str):
                    return md.strip()
    return ""


def _tool_names(tool_calls: Any) -> list[str]:
    if not isinstance(tool_calls, list):
        return []
    names: list[str] = []
    for call in tool_calls:
        if isinstance(call, dict) and isinstance(call.get("name"), str):
            names.append(call["name"])
    return names


def build_report(
    questions: list[dict[str, Any]],
    feedbacks: list[dict[str, Any]],
    *,
    days: int,
    limit: int = 20,
) -> ReviewReport:
    """Aggregate raw rows from chat.question_bank and chat.message_feedback into a ReviewReport."""
    status_counts = Counter(str(q["status"]) for q in questions)
    positive = sum(1 for fb in feedbacks if fb["rating"] == 1)
    negative = sum(1 for fb in feedbacks if fb["rating"] == -1)
    totals = {
        "questions": len(questions),
        "respondida": status_counts["respondida"],
        "necesita_tool": status_counts["necesita_tool"],
        "parcial": status_counts["parcial"],
        "fuera_de_alcance": status_counts["fuera_de_alcance"],
        "feedback_positive": positive,
        "feedback_negative": negative,
    }

    topic_questions: dict[str, list[str]] = {}
    for q in questions:
        if q["status"] == "necesita_tool":
            topic = (q.get("tool_name") or "sin tema").strip() or "sin tema"
            topic_questions.setdefault(topic, []).append(str(q["question"]))
    missing_tools = [
        MissingToolTopic(topic=topic, count=len(qs), samples=qs[:3])
        for topic, qs in sorted(topic_questions.items(), key=lambda kv: (-len(kv[1]), kv[0]))[
            :limit
        ]
    ]

    negative_feedback = [
        NegativeFeedbackItem(
            message_id=str(fb["message_id"]),
            question=str(fb.get("question") or ""),
            reason=fb.get("reason"),
            comment=fb.get("comment"),
            tools=_tool_names(fb.get("tool_calls")),
            trace_id=fb.get("trace_id"),
            created_at=str(fb["created_at"]),
        )
        for fb in feedbacks
        if fb["rating"] == -1
    ][:limit]

    partial_questions = [
        PartialQuestionItem(
            question=str(q["question"]),
            tool_name=q.get("tool_name"),
            created_at=str(q["created_at"]),
        )
        for q in questions
        if q["status"] == "parcial"
    ][:limit]

    return ReviewReport(
        days=days,
        totals=totals,
        missing_tools=missing_tools,
        negative_feedback=negative_feedback,
        partial_questions=partial_questions,
    )


async def collect_report(conn: AsyncConnection, *, days: int = 7, limit: int = 20) -> ReviewReport:
    """Read chat.question_bank and chat.message_feedback over the last `days` (0 = all)."""
    Q, M, F = ChatQuestionBank, ChatMessage, ChatMessageFeedback
    cutoff = datetime.now(UTC) - timedelta(days=days) if days > 0 else None

    q_stmt = select(Q.question, Q.status, Q.tool_name, Q.created_at).order_by(desc(Q.created_at))
    if cutoff is not None:
        q_stmt = q_stmt.where(Q.created_at >= cutoff)
    questions = [dict(r) for r in (await conn.execute(q_stmt)).mappings()]

    dir_msg = M.__table__.alias("dir_msg")
    prev_question = (
        select(dir_msg.c.blocks)
        .where(
            dir_msg.c.thread_id == M.thread_id,
            dir_msg.c.author == "director",
            dir_msg.c.created_at <= M.created_at,
        )
        .order_by(desc(dir_msg.c.created_at), desc(dir_msg.c.id))
        .limit(1)
        .scalar_subquery()
    )
    fb_stmt = (
        select(
            F.message_id,
            F.rating,
            F.reason,
            F.comment,
            F.created_at,
            M.tool_calls,
            M.trace_id,
            prev_question.label("question_blocks"),
        )
        .join(M, M.id == F.message_id)
        .order_by(desc(F.created_at))
    )
    if cutoff is not None:
        fb_stmt = fb_stmt.where(F.created_at >= cutoff)
    feedbacks: list[dict[str, Any]] = []
    for r in (await conn.execute(fb_stmt)).mappings():
        item = dict(r)
        item["question"] = _question_text(item.pop("question_blocks", None))
        feedbacks.append(item)

    return build_report(questions, feedbacks, days=days, limit=limit)


def draft_cases(report: ReviewReport, *, max_cases: int = 5) -> list[str]:
    """Draft Case(...) snippets from negative feedback and partial questions for eval/bank.py."""
    seen: set[str] = set()
    snippets: list[str] = []

    def add(question: str, tools: list[str], source: str) -> None:
        cleaned = question.strip()
        if not cleaned or cleaned in seen or len(snippets) >= max_cases:
            return
        seen.add(cleaned)
        case_id = f"rev-{_slug(cleaned)}"
        tool_tuple = ", ".join(repr(t) for t in tools) + ("," if len(tools) == 1 else "")
        snippets.append(
            "Case(\n"
            f"    {case_id!r},\n"
            f"    {cleaned!r},\n"
            '    "copilot",\n'
            f"    tools=({tool_tuple}),\n"
            "    facts=(),\n"
            f"    source={source!r},\n"
            "),"
        )

    for fb in report.negative_feedback:
        detail = f"feedback negativo ({fb.reason or 'sin motivo'})"
        add(fb.question, fb.tools, detail)
    for pq in report.partial_questions:
        add(pq.question, [pq.tool_name] if pq.tool_name else [], "pregunta parcial")
    return snippets


def format_text(report: ReviewReport) -> str:
    window = f"últimos {report.days} días" if report.days > 0 else "todo el historial"
    t = report.totals
    lines = [
        f"chat-review ({window})",
        f"  Preguntas: {t.get('questions', 0)} "
        f"(respondida: {t.get('respondida', 0)}, "
        f"necesita_tool: {t.get('necesita_tool', 0)}, "
        f"parcial: {t.get('parcial', 0)}, "
        f"fuera_de_alcance: {t.get('fuera_de_alcance', 0)})",
        f"  Feedback: 👍 {t.get('feedback_positive', 0)} · 👎 {t.get('feedback_negative', 0)}",
    ]

    if report.missing_tools:
        lines.append("\nBacklog de herramientas (necesita_tool):")
        for item in report.missing_tools:
            samples = " | ".join(item.samples)
            lines.append(f"  - {item.topic} ({item.count}): {samples}")

    if report.negative_feedback:
        lines.append("\nFeedback negativo:")
        for fb in report.negative_feedback:
            parts = [fb.reason or "sin motivo"]
            if fb.tools:
                parts.append("tools=" + ",".join(fb.tools))
            if fb.trace_id:
                parts.append(f"trace={fb.trace_id}")
            lines.append(f"  - «{fb.question}» [{'; '.join(parts)}]")
            if fb.comment:
                lines.append(f"    Comentario: {fb.comment}")

    if report.partial_questions:
        lines.append("\nPreguntas parciales recientes:")
        for pq in report.partial_questions:
            tool = pq.tool_name or "sin tool"
            lines.append(f"  - «{pq.question}» ({tool})")

    cases = draft_cases(report)
    if cases:
        lines.append("\nBorrador de casos para src/chat/eval/bank.py:")
        lines.extend(cases)

    return "\n".join(lines)


def to_json(report: ReviewReport) -> str:
    return json.dumps(asdict(report), ensure_ascii=False, indent=2)
