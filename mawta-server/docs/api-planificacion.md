# Planning API (term planning)

Contract for the term-planning flow: a teacher plans one class's term as
learning experiences, each with competencies, evaluation criteria, planned
evidences and a light session outline. It covers planning only (moment ①);
recording evidence during the term, "no class today", extending an experience
and closing the term come in later contracts.

The flow and its rules are decided outside this repository
(`flujo-planificacion-evaluacion-mawta.md`); this document is what the server
and the UI build against. The tables come from migration `00002`.

## Conventions

Same as the rest of the API:

- Prefix `/api/v1`; every route requires a session (`sessionAuth`) and checks
  that the teacher can access the class (`requireClassAccess`), directly or
  through the experience's class.
- JSON in `snake_case`; dates are `YYYY-MM-DD`; ids are UUIDs.
- Deletion is `POST …/delete` (soft delete).
- Errors: `{"error": {"code": "...", "message": "...", "hint": "..."}}`. The
  domain codes below are stable so the UI can show its own text.

## Decisions

1. **Saved step by step.** An experience is created as a draft on the first
   step and every later step writes to the database; "Revisar y guardar" only
   confirms it. Nothing is lost if the phone closes halfway, and the planning
   agent writes its proposals straight into the same rows.
2. **Generation runs in the background.** "Generar con Mawta" starts a
   generation and returns at once; the app polls it. Generating can take
   10–30 seconds, and the multi-agent design runs agents as queued jobs.
3. **Non-teaching days come from onboarding.** The school's file lists them, so
   the calendar and the session count exclude holidays and vacations.
4. **Mawta proposes, the teacher decides.** Everything generated is stored with
   `proposed_by = "mawta"` and `accepted_at = null` (pending) until the teacher
   accepts or edits it. Nothing is generated unless the teacher asks, and only
   gaps are filled.
5. **Standards are not used for criteria.** Criteria come from the grade's
   performances (`desempeños`); standards are only the reference for the
   descriptive conclusion at term close.

## Schema changes this contract needs (ticket 4)

- `learning_experiences.status`: `borrador` (default) or `planificada`. The
  overlap exclusion still applies to drafts, so two drafts cannot take the same
  weeks either.
- Onboarding: `dias_no_lectivos` in the school file (`fecha` or `desde`/`hasta`,
  `tipo` = `feriado` | `vacaciones` | `gestion`, optional `nombre`), loaded into
  `non_teaching_days`. Generated `class_sessions` skip those dates.

## Reads

### `GET /classes/{classID}/plan?term_id=`

"Tu trimestre". Without `term_id`, the term that contains today, or else the
next one.

```json
{
  "term": {"id": "…", "name": "Trimestre II", "starts_on": "2026-06-15", "ends_on": "2026-09-11",
           "status": "active"},
  "non_teaching_days": [{"from": "2026-07-27", "to": "2026-08-07", "kind": "vacaciones", "label": "Vacaciones de medio año"}],
  "class_dates_total": 38,
  "experiences": [
    {"id": "…", "title": "La tiendita escolar", "status": "planificada",
     "starts_on": "2026-06-15", "ends_on": "2026-07-10", "class_dates": 8,
     "competencies": [{"id": "…", "code": "MAT-C1", "name": "Resuelve problemas de cantidad",
                       "capabilities_total": 4, "capabilities_with_criteria": 3}],
     "pending_proposals": 0}
  ],
  "competencies": [
    {"id": "…", "code": "MAT-C1", "name": "Resuelve problemas de cantidad",
     "status": "planificada", "terms_worked": [1, 2],
     "capabilities_total": 4, "capabilities_covered_this_term": 3}
  ]
}
```

- `class_dates`: distinct dates with a scheduled session of the class in the
  range, excluding non-teaching days (a double block is one date).
- Competency `status`, computed (no stored summary):
  - `planificada`: it has a non-deleted experience in this term;
  - `toca`: otherwise, if it still needs terms to reach two worked terms in the
    year and the terms left (this one included) are no more than it needs;
  - `puede_esperar`: otherwise.
- The class's area competencies come first, then the transversal ones the
  school assigns to classes.

### `GET /classes/{classID}/curriculum`

Competencies of the class's area (and transversal ones), each with its
capabilities and the performances of the class's grade. No standards.

```json
{
  "grade": {"code": "1S", "cycle": "ciclo_vi", "expected_level": 6},
  "competencies": [
    {"id": "…", "code": "MAT-C1", "name": "Resuelve problemas de cantidad", "kind": "area",
     "capabilities": [{"id": "…", "code": "MAT-C1-CAP1", "name": "Traduce cantidades a expresiones numéricas"}],
     "performances": [{"id": "…", "order": 1, "text": "Establece relaciones entre datos…",
                       "en_proceso": true, "suggested_capability_id": null}]}
  ]
}
```

### `GET /classes/{classID}/calendar?from=&to=`

Dates with class and non-teaching days in the range (at most one term long),
for choosing experience dates and laying out sessions.

```json
{
  "class_dates": ["2026-06-16", "2026-06-18"],
  "non_teaching_days": [{"date": "2026-06-29", "kind": "feriado", "label": "San Pedro y San Pablo"}]
}
```

### `GET /experiences/{experienceID}`

The whole experience for the review, criteria, evidences, sessions and summary
screens.

```json
{
  "id": "…", "class_id": "…", "term_id": "…", "status": "borrador",
  "title": "La tiendita escolar", "idea_text": "…", "situation_text": "…",
  "starts_on": "2026-06-15", "ends_on": "2026-07-10",
  "competencies": [{"id": "…", "code": "MAT-C1", "name": "…"}],
  "criteria": [
    {"id": "…", "competency_id": "…", "description": "…",
     "capability_ids": ["…"], "performance_id": "…",
     "proposed_by": "mawta", "accepted_at": null}
  ],
  "evidences": [
    {"id": "…", "name": "Lista de precios de la tiendita", "kind": "produccion",
     "criterion_ids": ["…"], "session_date": "2026-06-25",
     "proposed_by": "teacher", "accepted_at": "2026-06-10T14:02:00Z"}
  ],
  "sessions": [
    {"date": "2026-06-16", "title": "¿Qué vendemos?", "topics": "…", "planned_evidence_id": null,
     "proposed_by": "mawta", "accepted_at": null}
  ],
  "class_dates": ["2026-06-16", "2026-06-18"],
  "warnings": [
    {"code": "capability_without_criterion", "competency_id": "…", "capability_id": "…"},
    {"code": "pending_proposals", "count": 3}
  ]
}
```

Warnings never block; they are what the summary screen shows.

## Experience

| Route | Body | Result |
|---|---|---|
| `POST /classes/{classID}/experiences` | `term_id`, `title`, `idea_text`, `situation_text`, `starts_on`, `ends_on`, `competency_ids` (≥1) | `201` with the experience, `status = "borrador"` |
| `PUT /experiences/{experienceID}` | any of `title`, `situation_text`, `starts_on`, `ends_on`, `competency_ids` | `200` with the experience |
| `POST /experiences/{experienceID}/confirm` | — | `200`, `status = "planificada"`, with `warnings` |
| `POST /experiences/{experienceID}/delete` | — | `204`; its criteria, evidences and sessions go with it |

Changing dates keeps sessions inside the new range and rejects the change if a
session or a placed evidence would fall outside (`date_not_in_experience`).
Removing a competency that has criteria is rejected (`competency_has_criteria`);
the teacher deletes those criteria first.

## Criteria

| Route | Body |
|---|---|
| `POST /experiences/{experienceID}/criteria` | `competency_id` (one of the experience's), `description`, `capability_ids` (≥1, of that competency), `performance_id` (a performance of that competency for the class's grade) |
| `PUT /criteria/{criterionID}` | any of `description`, `capability_ids`, `performance_id`; editing a proposal also accepts it |
| `POST /criteria/{criterionID}/accept` | — accepts a proposal unchanged |
| `POST /criteria/{criterionID}/delete` | — (existing route; also removes it from evidences) |

## Planned evidences

| Route | Body |
|---|---|
| `POST /experiences/{experienceID}/evidences` | `name`, `kind` (`produccion` \| `actuacion` \| `prueba_escrita`), `criterion_ids` (≥1, of this experience, any of its competencies), optional `session_date` |
| `PUT /evidences/{evidenceID}` | any of the above; editing a proposal also accepts it |
| `POST /evidences/{evidenceID}/accept` | — |
| `POST /evidences/{evidenceID}/delete` | — |

`session_date` places the evidence in that date's session entry, which must
exist. Placement is one relation seen from both sides: setting an evidence's
`session_date` and setting a session's `planned_evidence_id` are the same
change, and the server keeps `planned_evidences.session_entry_id` and
`session_outline_entries.planned_evidence_id` in step.

## Session outline

One entry per class date of the experience.

| Route | Body |
|---|---|
| `PUT /experiences/{experienceID}/sessions/{date}` | `title`, optional `topics`, optional `planned_evidence_id`; creates or replaces that date's entry, and accepts it |
| `POST /experiences/{experienceID}/sessions/{date}/accept` | — |
| `POST /experiences/{experienceID}/sessions/{date}/delete` | — |

`date` must be a class date inside the experience and not a non-teaching day.

## Generate with Mawta (implemented with the planning agent, ticket 6)

Ticket 4 does not implement these routes; they arrive with the planning agent
in ticket 6, together with the table they need:

- `planning_generations` (tenant-scoped, RLS like every school table): id,
  class, experience (null for an experience proposal), kind
  (`experience`, `criteria`, `evidences`, `sessions`), requested by, status
  (`pending`, `running`, `completed`, `failed`), input, result, error,
  timestamps. The queued job only carries the generation id: the `jobs` table
  has no RLS and no result column, so it is never exposed.

Each route creates a generation and returns `202` with it at once:
`{"id": "…", "kind": "criteria", "status": "pending"}`.

| Route | Body | What a completed generation did |
|---|---|---|
| `POST /classes/{classID}/experience-proposals` | `term_id`, `idea_text`, optional `competency_ids` | `result` holds a proposal (`title`, `situation_text`, `competency_ids`, `starts_on`, `ends_on`). **Not saved**: the app shows it for review, then calls `POST …/experiences` |
| `POST /experiences/{experienceID}/criteria/generate` | `competency_id` | Inserted pending criteria for that competency's capabilities without one |
| `POST /experiences/{experienceID}/evidences/generate` | — | Inserted pending evidences over the experience's criteria |
| `POST /experiences/{experienceID}/sessions/generate` | — | Inserted pending entries on class dates without one |
| `GET /generations/{generationID}` | — | `status`, `result` (ids of what was inserted, or the proposal), `error` |

The agent only uses the loaded curriculum (a criterion citing a capability or
performance that does not exist is discarded), respects the class dates and the
term end, and never suggests achievement levels. A second generation of the same
kind for the same experience while one is pending returns the pending one.

## Domain errors

| Code | Status | When |
|---|---|---|
| `experience_overlap` | 409 | The dates cross another experience of the class (drafts included) |
| `outside_term` | 422 | The experience starts before or ends after its term |
| `competency_not_in_subject` | 422 | A competency is not of the class's area (or an assigned transversal one) |
| `competency_has_criteria` | 409 | Removing a competency that still has criteria |
| `capability_not_in_competency` | 422 | A criterion capability belongs to another competency |
| `criterion_needs_capability` | 422 | A criterion with no capability |
| `performance_not_in_grade` | 422 | The performance is of another competency or grade |
| `criterion_other_experience` | 422 | An evidence uses a criterion of another experience |
| `date_not_in_experience` | 422 | A session or placed evidence date outside the experience, not a class date, or a non-teaching day |
| `experience_not_draft` | 409 | Confirming an experience that is already planned |
| `generation_failed` | 200 (in the generation) | The agent could not produce a valid result; `error` says why |

## Out of scope

"No hubo clase" and re-planning, extending an experience, recording evidence,
term close (coverage, levels, descriptive conclusions), per-student
adjustments, the "Hoy" view, and the session-detail agent.
