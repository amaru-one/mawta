"""Mawta's name sweep over voice-note transcripts.

A teacher speaks freely about a student and may name the student, classmates, relatives or other
teachers, and speech-to-text misspells names; none of that may reach the descriptive-conclusions
agent or a SIAGIE text. The sweep is done by a model, because recognising a misspelled name or a
nickname needs context: it reads the transcript with the assigned student's names and the section
roster, and points at every reference to a person. It never rewrites the transcript. The server
checks each fragment against the transcript, replaces it ([ESTUDIANTE], [COMPAÑERO_n], [PERSONA]),
records one voice_note_redactions row per replacement, and decides from the references whether
the note belongs to its assigned student.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import UUID

from psycopg import AsyncConnection

from mawta_api.agent import InvalidAnswer, Prepared, Spec
from mawta_api.agent.enqueue import enqueue
from mawta_api.agent.llm import Block, Tool
from mawta_api.agent.redaction.replace import Fragment, LocateError, attribution, locate, redact
from mawta_api.errors import NotFound
from mawta_api.repo import redaction as repo
from mawta_api.repo.events import log_event
from mawta_api.repo.roster import roster_as_of

NAME = "redaction"  # the agent_generations.agent value of this agent
KIND_VOICE_NOTE = "voice_note"  # the only thing this agent sweeps
PROMPT_VERSION = "redaction-2026-10-09.1"  # changes whenever prompts/ change
ASSIGNED_KEY = "S0"

_PROMPTS = Path(__file__).parent / "prompts"


def _prompt(name: str) -> str:
    return (_PROMPTS / f"{name}.md").read_text()


def target_key(voice_note_id: UUID, student_id: UUID) -> str:
    """Identifies a sweep. It includes the student, so a note moved to another student is swept
    again even while an earlier sweep is in flight."""
    return f"redaction:voice_note:{voice_note_id}:student:{student_id}"


async def queue(
    conn: AsyncConnection,
    tenant_id: UUID,
    note: dict,
    requested_by: UUID,
    reassigned: bool,
) -> None:
    """Start the sweep of a voice note in the caller's transaction. A note without a transcript
    yet is left alone (its transcription queues it later); a blank transcript is discarded as
    unreadable without calling the model."""
    if note["transcript"] is None:
        return
    if not note["transcript"].strip():
        await repo.set_voice_note_attribution(
            conn, note["id"], None, repo.ATTRIBUTION_DISCARDED, repo.DISCARD_UNREADABLE
        )
        return
    await enqueue(
        conn,
        tenant_id,
        agent=NAME,
        kind=KIND_VOICE_NOTE,
        class_id=note["class_id"],
        student_id=note["student_id"],
        voice_note_id=note["id"],
        requested_by=requested_by,
        target_key=target_key(note["id"], note["student_id"]),
        input={"reassigned": reassigned},
    )


async def queue_after_transcript(conn: AsyncConnection, voice_note_id: UUID) -> None:
    """The hook the transcription job runs once a transcript is saved: queues the sweep, requested
    by the teacher who recorded the note."""
    note = await repo.get_voice_note_for_redaction(conn, voice_note_id)
    tenant_id = await repo.current_tenant_id(conn)
    await queue(conn, tenant_id, note, note["teacher_id"], False)


SWEEP_TOOL = Tool(
    name="marcar_personas",
    description="Points at every reference to a person in the transcript. Never rewrites the "
    "transcript.",
    properties={
        "fragments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "The words exactly as they appear in the transcript, "
                        "including misspellings.",
                    },
                    "refers_to": {
                        "type": "string",
                        "enum": [
                            repo.REFERS_TO_ASSIGNED_STUDENT,
                            repo.REFERS_TO_CLASSMATE,
                            repo.REFERS_TO_OTHER_PERSON,
                        ],
                    },
                    "student_key": {
                        "type": "string",
                        "description": "For a classmate, its key (S1, S2…). Empty otherwise.",
                    },
                },
                "required": ["text", "refers_to", "student_key"],
            },
        },
        "unreadable": {
            "type": "boolean",
            "description": "True only when the transcript is noise or has no recognisable meaning.",
        },
    },
    required=["fragments", "unreadable"],
)


@dataclass
class _State:
    """What prepare read, handed back to apply."""

    voice_note_id: UUID
    student_id: UUID
    transcript: str
    reassigned: bool
    # Maps each roster key the model sees to the student.
    classmates: dict[str, UUID] = field(default_factory=dict)


def _describe(n: dict) -> str:
    """Every name a teacher might use for a student."""
    parts = [f"given name {n['given_name']}"]
    if n["preferred_name"] and n["preferred_name"].strip():
        parts.append(f"goes by {n['preferred_name']}")
    surnames = n["paternal_surname"]
    if n["maternal_surname"]:
        surnames += " " + n["maternal_surname"]
    parts.append(f"surnames {surnames}")
    return "; ".join(parts)


def _parse_answer(raw: Any) -> tuple[list[Fragment], bool]:
    try:
        fragments = [
            Fragment(
                text=_str(f["text"]),
                refers_to=_str(f["refers_to"]),
                student_key=_str(f.get("student_key")),
            )
            for f in (raw.get("fragments") or [])
        ]
        unreadable = raw.get("unreadable") or False
        if not isinstance(unreadable, bool):
            raise TypeError("unreadable")
    except (AttributeError, KeyError, TypeError) as exc:
        raise InvalidAnswer(f"la respuesta no tiene el formato de la herramienta: {exc}") from None
    return fragments, unreadable


def _str(value: Any) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise TypeError("expected a string")
    return value


class RedactionAgent:
    name = NAME
    prompt_version = PROMPT_VERSION

    async def prepare(self, conn: AsyncConnection, gen: dict) -> Prepared:
        if gen["voice_note_id"] is None:
            raise RuntimeError(f"redaction: generation {gen['id']} has no voice note")
        reassigned = bool((gen["input"] or {}).get("reassigned"))
        note = await repo.get_voice_note_for_redaction(
            conn, gen["voice_note_id"]
        )  # NotFound: final
        if gen["student_id"] is not None and note["student_id"] != gen["student_id"]:
            # Moved to another student since this sweep was queued; the move queued its own sweep.
            return Prepared(result={"skipped": "reassigned"})
        if note["transcript"] is None or not note["transcript"].strip():
            return Prepared(result={"skipped": "no_transcript"})

        roster = await roster_as_of(conn, note["class_id"], note["recorded_at"].date())
        names = await repo.student_names(conn, [note["student_id"], *roster])
        st = _State(
            voice_note_id=note["id"],
            student_id=note["student_id"],
            transcript=note["transcript"],
            reassigned=reassigned,
        )
        lines = ["Assigned student (the note was recorded about this student):"]
        lines += [
            f"- {ASSIGNED_KEY}: {_describe(n)}" for n in names if n["id"] == note["student_id"]
        ]
        lines += ["", "Classmates in the same section:"]
        k = 0
        for n in names:
            if n["id"] == note["student_id"]:
                continue
            k += 1
            key = f"S{k}"
            st.classmates[key] = n["id"]
            lines.append(f"- {key}: {_describe(n)}")
        if k == 0:
            lines.append("- (none)")
        lines += ["", f"<transcript>\n{st.transcript}\n</transcript>", ""]
        return Prepared(
            spec=Spec(
                system=[Block(_prompt("redaction"), cache=True)],
                prompt="\n".join(lines),
                tool=SWEEP_TOOL,
                max_tokens=2000,
            ),
            state=st,
        )

    async def apply(self, conn: AsyncConnection, gen: dict, prepared: Prepared, answer: Any) -> Any:
        st: _State = prepared.state
        fragments, unreadable = _parse_answer(answer)
        for f in fragments:
            f.text = f.text.strip()
            f.student_key = f.student_key.strip()
            if not f.text:
                raise InvalidAnswer("un fragmento viene vacío")
            if f.refers_to == repo.REFERS_TO_CLASSMATE:
                if f.student_key not in st.classmates:
                    raise InvalidAnswer(
                        f'el fragmento "{f.text}" es de un compañero pero student_key '
                        f'"{f.student_key}" no está en la lista'
                    )
            elif f.refers_to in (repo.REFERS_TO_ASSIGNED_STUDENT, repo.REFERS_TO_OTHER_PERSON):
                f.student_key = ""
            else:
                raise InvalidAnswer(f'refers_to "{f.refers_to}" no es válido')

        # The note may have changed while the model answered: never write a sweep of a transcript
        # or a student it no longer has.
        try:
            note = await repo.get_voice_note_for_redaction(conn, st.voice_note_id)
        except NotFound:
            raise
        if (
            note["student_id"] != st.student_id
            or note["transcript"] is None
            or note["transcript"] != st.transcript
        ):
            return {"skipped": "note_changed"}

        spans = []
        if not unreadable:
            try:
                spans = locate(st.transcript, fragments)
            except LocateError as exc:
                raise InvalidAnswer(str(exc)) from None
        status, reason = attribution(spans, unreadable, st.reassigned)
        await repo.supersede_voice_note_redactions(conn, st.voice_note_id)
        redacted = None
        if not unreadable:
            redacted, tokens = redact(st.transcript, spans)
            for s, token in zip(spans, tokens, strict=True):
                await repo.insert_voice_note_redaction(
                    conn,
                    voice_note_id=st.voice_note_id,
                    generation_id=gen["id"],
                    student_id=st.student_id,
                    original_text=st.transcript[s.start : s.end],
                    start_offset=s.start,
                    end_offset=s.end,
                    replacement=token,
                    refers_to=s.frag.refers_to,
                    matched_student_id=(
                        st.classmates[s.frag.student_key]
                        if s.frag.refers_to == repo.REFERS_TO_CLASSMATE
                        else None
                    ),
                )
        await repo.set_voice_note_attribution(conn, st.voice_note_id, redacted, status, reason)
        action = (
            "voice_note.attribution_discarded"
            if status == repo.ATTRIBUTION_DISCARDED
            else "voice_note.redacted"
        )
        await log_event(
            conn,
            action,
            "voice_note",
            st.voice_note_id,
            {
                "attribution_status": status,
                "discard_reason": reason,
                "replacements": len(spans),
            },
            st.student_id,
            gen["class_id"],
        )
        return {
            "replacements": len(spans),
            "attribution_status": status,
            "discard_reason": reason,
        }
