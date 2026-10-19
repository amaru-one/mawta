"""Mawta's descriptive-conclusions agent (port of agent/conclusions).

It proposes the conclusión descriptiva of one student in one competency and term ("juicio docente
basado en evidencias […] Señala avances, dificultades y recomendaciones", RVM 094-2020, glossary)
from the competency's criteria and capabilities, the student's evidences of the term and the
teacher's voice notes, already swept of names.

One bounded call, like the planning agent: the server gathers all the material, the model answers
by filling a fixed schema, and every avance and dificultad must cite the evidences or notes it
rests on. It never suggests or contests the level: the level is the teacher's judgement and is
asserted first. The proposal stays in agent_generations.result until the teacher saves it as a
conclusion; it is never saved on their behalf.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import UUID

from psycopg import AsyncConnection

from mawta_api import domain
from mawta_api.agent import InvalidAnswer, Prepared, Spec
from mawta_api.agent.conclusions.guard import guard, name_words
from mawta_api.agent.llm import Block, Tool
from mawta_api.errors import AppError
from mawta_api.repo import conclusion_context as ctx_repo
from mawta_api.repo.home import tenant_today
from mawta_api.repo.redaction import current_tenant_id

# The one difficulty a student at AD may have when the material shows none: the norm still asks
# every conclusion to state them.
NO_DIFFICULTIES_AD = "No presenta dificultades significativas en esta competencia."

NAME = "conclusions"  # the agent_generations.agent value of this agent
KIND_CONCLUSION = "conclusion"  # what this agent generates
PROMPT_VERSION = "conclusions-2026-10-14.1"  # changes whenever prompts/ change

# The least evidence a conclusion can stand on: the teacher-asserted level plus this many distinct
# evidences with a live graded score. Voice notes never count toward it: they complement, they do
# not ground.
MIN_GRADED_EVIDENCES = ctx_repo.MIN_CONCLUSION_EVIDENCES

_PROMPTS = Path(__file__).parent / "prompts"


def _prompt(name: str) -> str:
    return (_PROMPTS / f"{name}.md").read_text()


@dataclass(frozen=True)
class Scope:
    """What one conclusion is about. It always comes from the server (the request path or the
    generation's columns), never from the model."""

    class_id: UUID
    student_id: UUID
    competency_id: UUID
    term_id: UUID


def target_key(s: Scope) -> str:
    """One conclusion generation at a time per student, competency and term."""
    return f"conclusions:student:{s.student_id}:comp:{s.competency_id}:term:{s.term_id}"


def scope_of(gen: dict) -> Scope:
    if gen["student_id"] is None or gen["competency_id"] is None or gen["term_id"] is None:
        raise RuntimeError(f"conclusions: generation {gen['id']} has no scope")
    return Scope(gen["class_id"], gen["student_id"], gen["competency_id"], gen["term_id"])


ERR_LEVEL_REQUIRED = AppError(
    422,
    "level_required",
    "Primero registra el nivel de logro de esta competencia: la conclusión explica ese nivel.",
)
ERR_INSUFFICIENT_EVIDENCE = AppError(
    422,
    "insufficient_evidence",
    f"Hay poca evidencia para esta competencia: Mawta necesita al menos {MIN_GRADED_EVIDENCES} "
    "evidencias valoradas. Puedes escribir la conclusión a mano.",
)

# Warning codes.
# Some notes were discarded but others were used: the teacher is told how many, and does not see
# them.
WARN_VOICE_NOTES_DISCARDED = "voice_notes_discarded"
# Every note of the student was discarded: the worst case, the only one where the teacher is shown
# the discarded notes to move or confirm.
WARN_ALL_VOICE_NOTES_DISCARDED = "all_voice_notes_discarded"
WARN_VOICE_NOTES_PENDING = "voice_notes_pending"
# No note at all: the proposal is less precise.
WARN_NO_VOICE_NOTES = "no_voice_notes"
# The graded evidence is all one kind (produccion or actuacion): the CNEB asks for varied
# evidence. Never blocks: the proposal still runs.
WARN_EVIDENCE_SINGLE_KIND = "evidence_single_kind"
# The graded evidence all comes from one learning experience: the CNEB asks for evidence from
# diverse situations.
WARN_EVIDENCE_SINGLE_EXPERIENCE = "evidence_single_experience"


@dataclass
class Material:
    """Everything the agent may read for one scope."""

    scope: Scope
    level: str | None = None
    requirement: str = ""
    competency: dict = field(default_factory=dict)
    evidences: list[dict] = field(default_factory=list)
    voice_notes: list[dict] = field(default_factory=list)
    note_counts: dict = field(default_factory=lambda: {"discarded": 0, "pending": 0})
    earlier: list[dict] = field(default_factory=list)
    graded: int = 0

    def check(self) -> None:
        """Raise why the material is not enough to propose a conclusion."""
        if self.level is None:
            raise ERR_LEVEL_REQUIRED
        if self.graded < MIN_GRADED_EVIDENCES:
            raise ERR_INSUFFICIENT_EVIDENCE

    def only_discarded_notes(self) -> bool:
        """The worst case: the student has voice notes in the term, and the sweep discarded
        every one of them."""
        return not self.voice_notes and self.note_counts["discarded"] > 0

    def _variety_warnings(self) -> list[dict]:
        """Graded evidence that is narrow: one kind, or one experience. Only speaks once the
        minimum is met, and only about graded evidence. Evidence the teacher added by hand has
        no experience, so it never proves a single experience on its own."""
        if self.graded < MIN_GRADED_EVIDENCES:
            return []
        out: list[dict] = []
        kinds: set[str] = set()
        experience: UUID | None = None
        single_experience = True
        for e in self.evidences:
            if not ctx_repo.graded(e):
                continue
            kinds.add(e["kind"])
            if e["experience_id"] is None:
                single_experience = False
            elif experience is None:
                experience = e["experience_id"]
            elif experience != e["experience_id"]:
                single_experience = False
        if len(kinds) == 1:
            out.append({"code": WARN_EVIDENCE_SINGLE_KIND, "kind": next(iter(kinds))})
        if single_experience and experience is not None:
            out.append({"code": WARN_EVIDENCE_SINGLE_EXPERIENCE})
        return out

    def warnings(self) -> list[dict]:
        """What the teacher should know about this material."""
        out: list[dict] = []
        discarded, pending = self.note_counts["discarded"], self.note_counts["pending"]
        if self.only_discarded_notes():
            out.append({"code": WARN_ALL_VOICE_NOTES_DISCARDED, "count": discarded})
        elif discarded > 0:
            out.append({"code": WARN_VOICE_NOTES_DISCARDED, "count": discarded})
        if pending > 0:
            out.append({"code": WARN_VOICE_NOTES_PENDING, "count": pending})
        if not self.voice_notes and discarded == 0:
            out.append({"code": WARN_NO_VOICE_NOTES})
        return out + self._variety_warnings()


async def gather(conn: AsyncConnection, s: Scope) -> Material:
    """Read the material of a scope."""
    m = Material(scope=s)
    m.level = await ctx_repo.live_competency_level(conn, s.student_id, s.competency_id, s.term_id)
    m.requirement = await ctx_repo.conclusion_requirement(
        conn, s.class_id, s.student_id, s.competency_id, s.term_id
    )
    m.competency = await ctx_repo.get_competency_brief(conn, s.competency_id)
    m.evidences = await ctx_repo.list_conclusion_evidence(
        conn, s.class_id, s.student_id, s.competency_id, s.term_id
    )
    m.voice_notes, m.note_counts = await ctx_repo.list_conclusion_voice_notes(
        conn, s.class_id, s.student_id, s.term_id
    )
    m.earlier = await ctx_repo.list_earlier_term_conclusions(
        conn, s.student_id, s.competency_id, s.term_id
    )
    m.graded = sum(1 for e in m.evidences if ctx_repo.graded(e))
    return m


@dataclass
class Refs:
    """The short references the model cites (E1, N1, C1) and the ids they stand for. Short
    references are easier to copy exactly than UUIDs, and the model never sees an id it could
    carry elsewhere."""

    evidences: dict[str, UUID] = field(default_factory=dict)
    voice_notes: dict[str, UUID] = field(default_factory=dict)
    capabilities: dict[UUID, str] = field(default_factory=dict)


_REQUIREMENT_TEXT = {
    "level_c": "The level is C, so the conclusion is mandatory.",
    "level_b": "The level is B and, at this stage, the conclusion is mandatory.",
    "level_a": "The level is A and, at this stage, the conclusion is mandatory.",
    "cycle_i_mandatory": "Every competency carries a conclusion at this stage.",
    "consecutive_c": "The level is C for the second consecutive term. The conclusion is mandatory "
    "AND must justify why there was no progress (fill justificacion_sin_progreso).",
    "inclusion_support": "The student faces barriers to learning and receives inclusion support. "
    "The conclusion is mandatory every term AND must state the supports and reasonable "
    "adjustments provided (fill apoyos_brindados).",
    "optional": "The conclusion is optional here; the teacher asked for one.",
}


def _trim_float(value: float) -> str:
    """strconv.FormatFloat(f, 'f', -1, 64): the shortest form, no exponent, no trailing zero."""
    text = repr(float(value))
    if "e" in text or "E" in text:
        text = f"{value:f}".rstrip("0").rstrip(".")
    elif text.endswith(".0"):
        text = text[:-2]
    return text


def _kind_text(kind: str) -> str:
    if kind == "actuacion":
        return "actuación: something the students did in front of others"
    return "producción: something the students made"


def _score_text(e: dict) -> str:
    status = e["score_status"]
    if status is None:
        return "not assessed yet"
    if status == "graded":
        if e["scale_level"] is not None:
            return f"level {e['scale_level']} on this evidence"
        if e["raw_value"] is not None and e["max_value"] is not None:
            return f"{_trim_float(e['raw_value'])} out of {_trim_float(e['max_value'])}"
        return "assessed"
    return {
        "not_submitted": "did not submit it",
        "absent": "was absent",
        "excused": "excused",
    }.get(status, status)


def render(m: Material) -> tuple[str, Refs]:
    """The material as the user message, and the references it used."""
    r = Refs()
    comp = m.competency
    b = [f"Competency: {comp['code']} — {comp['name']}"]
    if comp["description"]:
        b.append(f"Description: {comp['description']}")
    b.append("Capabilities:")
    for i, c in enumerate(comp["capabilities"], start=1):
        key = f"C{i}"
        r.capabilities[c["id"]] = key
        b.append(f"- {key}: {c['name']}")
    b += [
        "",
        f"Achievement level asserted by the teacher for this term: {m.level}",
        _REQUIREMENT_TEXT.get(m.requirement, ""),
        "",
        "<evidences>",
    ]
    for i, e in enumerate(m.evidences, start=1):
        key = f"E{i}"
        r.evidences[key] = e["id"]
        b.append(
            f"- {key}: «{e['title']}» ({_kind_text(e['kind'])}). "
            f"Result for [ESTUDIANTE]: {_score_text(e)}"
        )
        if e["description"]:
            b.append(f"  What it asked: {e['description']}")
        for c in e["criteria"]:
            caps = [r.capabilities[cid] for cid in c["capability_ids"] if cid in r.capabilities]
            line = f"  Criterion: {c['description']}"
            if caps:
                line += f" (looks at {', '.join(caps)})"
            b.append(line)
        if e["feedback"] and e["feedback"].strip():
            b.append(f"  Teacher's feedback: {e['feedback'].strip()}")
    b += ["</evidences>", "", "<voice_notes>"]
    if not m.voice_notes:
        b.append("(none)")
    for i, n in enumerate(m.voice_notes, start=1):
        key = f"N{i}"
        r.voice_notes[key] = n["id"]
        head = f"- {key} ({n['recorded_at'].strftime('%Y-%m-%d')}"
        if n["session_topic"]:
            head += f", session «{n['session_topic']}»"
        b.append(f"{head}): {n['transcript_redacted']}")
    b.append("</voice_notes>")
    if m.earlier:
        b += ["", "<earlier_terms>"]
        for e in m.earlier:
            level = f"level {e['level']}" if e["level"] is not None else "no level"
            line = f"- {e['term_name']}: {level}"
            if e["body"]:
                line += f". Conclusion: {e['body']}"
            b.append(line)
        b.append("</earlier_terms>")
    return "\n".join(b) + "\n", r


def _point_items(description: str) -> dict:
    return {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {
                "texto": {"type": "string", "description": description},
                "evidencias": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "References of the evidences it rests on (E1, E2…).",
                },
                "notas": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "References of the voice notes it rests on (N1, N2…).",
                },
            },
            "required": ["texto", "evidencias", "notas"],
        },
    }


CONCLUSION_TOOL = Tool(
    name="proponer_conclusion",
    description="Records the proposed descriptive conclusion: progress, difficulties and "
    "recommendations, each grounded in the material. Joined into one paragraph, it must fit "
    "SIAGIE's 350 characters.",
    properties={
        "avances": _point_items(
            "One short sentence on something the student achieved, grounded in the cited material."
        ),
        "dificultades": _point_items(
            "One short sentence on something the student still finds difficult, grounded in the "
            "cited material. At least one is required."
        ),
        "recomendaciones": _point_items(
            "One short, personalised, actionable recommendation to keep developing the competency."
        ),
        "justificacion_sin_progreso": {
            "type": "string",
            "description": "Only for C in consecutive terms: why there was no progress. Empty "
            "otherwise.",
        },
        "apoyos_brindados": {
            "type": "string",
            "description": "Only for inclusion support: the supports and reasonable adjustments "
            "provided. Empty otherwise.",
        },
        "notas_no_usadas": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "nota": {"type": "string"},
                    "motivo": {
                        "type": "string",
                        "description": "Why it was not used, e.g. it is about behaviour, not this "
                        "competency.",
                    },
                },
                "required": ["nota", "motivo"],
            },
        },
    },
    required=[
        "avances",
        "dificultades",
        "recomendaciones",
        "justificacion_sin_progreso",
        "apoyos_brindados",
        "notas_no_usadas",
    ],
)


@dataclass
class _State:
    material: Material
    refs: Refs
    names: list[str]


def clean(text: str) -> str:
    return " ".join(text.split())


def sentence(text: str) -> str:
    """End a text with a period when it has no closing punctuation."""
    if not text or text[-1] in ".!?":
        return text
    return text + "."


def compose(res: dict) -> str:
    """The conclusion as SIAGIE receives it and the teacher edits it: one paragraph with progress,
    difficulties, the justification or supports when the norm asks for them, and the
    recommendations."""
    sentences = [sentence(p["text"]) for p in res["progress"]]
    sentences += [sentence(p["text"]) for p in res["difficulties"]]
    if res["no_progress_justification"]:
        sentences.append(sentence(res["no_progress_justification"]))
    if res["supports_provided"]:
        sentences.append(sentence(res["supports_provided"]))
    sentences += [sentence(p["text"]) for p in res["recommendations"]]
    return domain.normalize_conclusion(" ".join(sentences))


def _points(raw: Any, field_name: str) -> list[dict]:
    """The model's list of {texto, evidencias, notas}; wrong types are an unusable answer."""
    try:
        return [
            {
                "texto": _str(p["texto"]),
                "evidencias": _str_list(p.get("evidencias")),
                "notas": _str_list(p.get("notas")),
            }
            for p in (raw or [])
        ]
    except (KeyError, TypeError, AttributeError):
        raise InvalidAnswer(
            f"la respuesta no tiene el formato de la herramienta: {field_name}"
        ) from None


def _str(value: Any) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise TypeError("expected a string")
    return value


def _str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise TypeError("expected a list")
    return [_str(v) for v in value]


class ConclusionsAgent:
    name = NAME
    prompt_version = PROMPT_VERSION

    async def prepare(self, conn: AsyncConnection, gen: dict) -> Prepared:
        scope = scope_of(gen)
        m = await gather(conn, scope)
        m.check()  # final: the teacher reads why
        tenant_id = await current_tenant_id(conn)
        today = await tenant_today(conn, tenant_id)
        students = await ctx_repo.roster_names(conn, scope.class_id, scope.student_id, today)
        text, refs = render(m)
        return Prepared(
            spec=Spec(
                system=[Block(_prompt("conclusion"), cache=True)],
                prompt=text,
                tool=CONCLUSION_TOOL,
                max_tokens=3000,
            ),
            state=_State(m, refs, name_words(students)),
        )

    async def apply(self, conn: AsyncConnection, gen: dict, prepared: Prepared, answer: Any) -> Any:
        st: _State = prepared.state
        m = st.material
        if not isinstance(answer, dict):
            raise InvalidAnswer("la respuesta no tiene el formato de la herramienta: wrong type")
        avances = _points(answer.get("avances"), "avances")
        dificultades = _points(answer.get("dificultades"), "dificultades")
        recomendaciones = _points(answer.get("recomendaciones"), "recomendaciones")
        try:
            justification = _str(answer.get("justificacion_sin_progreso"))
            supports = _str(answer.get("apoyos_brindados"))
            unused = [
                {"nota": _str(u["nota"]), "motivo": _str(u["motivo"])}
                for u in (answer.get("notas_no_usadas") or [])
            ]
        except (KeyError, TypeError, AttributeError):
            raise InvalidAnswer(
                "la respuesta no tiene el formato de la herramienta: campos de texto"
            ) from None

        # The level may have changed while the model wrote: a conclusion that explains a level the
        # student no longer has is worse than none.
        level = await ctx_repo.live_competency_level(
            conn, m.scope.student_id, m.scope.competency_id, m.scope.term_id
        )
        if level is None or level != m.level:
            raise AppError(
                422,
                "level_changed",
                "El nivel de logro cambió mientras Mawta escribía. Vuelve a generar la conclusión.",
            )

        used: dict[UUID, bool] = {}
        used_ids: list[UUID] = []

        def convert(section: str, points: list[dict], must_cite: bool) -> list[dict]:
            out = []
            for pt in points:
                text = clean(pt["texto"])
                if not text:
                    continue
                if why := guard(text, st.names):
                    raise InvalidAnswer(why)
                cp = {"text": text, "evidence_ids": [], "voice_note_ids": []}
                for ref in pt["evidencias"]:
                    eid = st.refs.evidences.get(ref.strip())
                    if eid is None:
                        raise InvalidAnswer(
                            f'{section} cita la evidencia "{ref}", que no existe; usa solo '
                            f"E1…E{len(st.refs.evidences)}"
                        )
                    cp["evidence_ids"].append(eid)
                for ref in pt["notas"]:
                    nid = st.refs.voice_notes.get(ref.strip())
                    if nid is None:
                        raise InvalidAnswer(
                            f'{section} cita la nota "{ref}", que no existe; usa solo las '
                            "referencias N entregadas"
                        )
                    cp["voice_note_ids"].append(nid)
                    if not used.get(nid):
                        used[nid] = True
                        used_ids.append(nid)
                if must_cite and not cp["evidence_ids"] and not cp["voice_note_ids"]:
                    raise InvalidAnswer(
                        f"{section} «{text}» no cita ninguna evidencia ni nota; cada avance y "
                        "dificultad debe apoyarse en el material"
                    )
                out.append(cp)
            return out

        res: dict[str, Any] = {
            "body": "",
            "level": m.level,
            "requirement": m.requirement,
            "progress": convert("un avance", avances, True),
            "difficulties": convert("una dificultad", dificultades, True),
            "recommendations": convert("una recomendación", recomendaciones, False),
            "no_progress_justification": "",
            "supports_provided": "",
            "used_voice_note_ids": used_ids,
            "unused_voice_notes": [],
            "warnings": m.warnings(),
        }
        # RM 281-2016 (CNEB, VII): a conclusion "debe […] señalar avances, dificultades y
        # recomendaciones". All three, every time.
        if not res["progress"]:
            raise InvalidAnswer("la conclusión debe señalar al menos un avance")
        if not res["difficulties"]:
            raise InvalidAnswer(
                "la conclusión debe señalar al menos una dificultad; si el nivel es AD y el "
                f"material no muestra ninguna, escribe «{NO_DIFFICULTIES_AD}»"
            )
        if m.level != "AD":
            for d in res["difficulties"]:
                if sentence(d["text"]).casefold() == NO_DIFFICULTIES_AD.casefold():
                    raise InvalidAnswer(
                        f"el nivel es {m.level}: «{NO_DIFFICULTIES_AD}» solo vale en AD; señala "
                        "una dificultad que muestre el material"
                    )
        if not res["recommendations"]:
            raise InvalidAnswer(
                "toda conclusión debe incluir al menos una recomendación personalizada "
                "(5.1.1.3 p.7)"
            )
        res["no_progress_justification"] = clean(justification)
        res["supports_provided"] = clean(supports)
        if m.requirement == "consecutive_c" and not res["no_progress_justification"]:
            raise InvalidAnswer(
                "el nivel es C por segundo periodo consecutivo: justificacion_sin_progreso es "
                "obligatoria"
            )
        if m.requirement == "inclusion_support" and not res["supports_provided"]:
            raise InvalidAnswer(
                "el estudiante tiene apoyo de inclusión: apoyos_brindados es obligatorio"
            )
        for extra in (res["no_progress_justification"], res["supports_provided"]):
            if why := guard(extra, st.names):
                raise InvalidAnswer(why)
        for u in unused:
            nid = st.refs.voice_notes.get(u["nota"].strip())
            if nid is not None and not used.get(nid):
                res["unused_voice_notes"].append(
                    {"voice_note_id": nid, "reason": clean(u["motivo"])}
                )
        res["body"] = compose(res)
        n = domain.conclusion_length(res["body"])
        if n > domain.CONCLUSION_MAX_CHARS:
            raise InvalidAnswer(
                f"la conclusión tiene {n} caracteres y SIAGIE acepta como máximo "
                f"{domain.CONCLUSION_MAX_CHARS}: acórtala en al menos "
                f"{n - domain.CONCLUSION_MAX_CHARS} sin quitar el avance, la dificultad ni la "
                "recomendación"
            )
        # Optional fields are left out of the result when empty.
        if not res["no_progress_justification"]:
            del res["no_progress_justification"]
        if not res["supports_provided"]:
            del res["supports_provided"]
        return res
