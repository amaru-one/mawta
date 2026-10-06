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

"Tu trimestre". Without `term_id`, the term of the class's year that contains
today, or else the next one, or else the last one. A `term_id` of another year
is `404`.

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

- `class_dates`: distinct dates with a non-cancelled session of the class in
  the range, excluding non-teaching days (a double block is one date).
- `non_teaching_days`: runs of consecutive days with the same kind and label.
- Competency `status`, computed (no stored summary):
  - `planificada`: it has a non-deleted experience in this term;
  - `toca`: otherwise, if it still needs terms to reach two worked terms in the
    year and the terms left (this one included) are no more than it needs;
  - `puede_esperar`: otherwise.

  A worked term is a term of the year with a non-deleted experience (drafts
  included) of this class working the competency.
- Coverage (`capabilities_with_criteria`, `capabilities_covered_this_term`)
  counts accepted criteria only: a pending Mawta proposal is not planned work
  yet.
- Only the class's area competencies are listed. Transversal competencies are
  not, for now: the schema has no way to assign one to a class, and
  `check_competency_subject` (00002) only links area competencies to an
  experience.

### `GET /classes/{classID}/curriculum`

Competencies of the class's area, each with its capabilities and the
performances of the class's grade. No standards. `expected_level` comes from
`standard_level_mappings` (EBR) and is `null` when the grade has no cycle or
the mapping is missing.

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

Dates with class and non-teaching days in the range, for choosing experience
dates and laying out sessions. `from` and `to` are required, and the range may
be at most as long as the longest term of the year (`400 bad_request`
otherwise).

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
`capability_without_criterion` is listed for every capability of the
experience's competencies that no accepted criterion looks at.

Criteria and evidences also carry `experience_id`, so the same object can be
returned by the routes that name a criterion or an evidence directly.

## Experience

| Route | Body | Result |
|---|---|---|
| `POST /classes/{classID}/experiences` | `term_id`, `title`, `idea_text`, optional `situation_text`, `starts_on`, `ends_on`, `competency_ids` (≥1) | `201` with the experience, `status = "borrador"` |
| `PUT /experiences/{experienceID}` | any of `title`, `situation_text` (`""` clears it), `starts_on`, `ends_on`, `competency_ids` (the whole new list) | `200` with the experience |
| `POST /experiences/{experienceID}/confirm` | — | `200`, `status = "planificada"`, with `warnings` |
| `POST /experiences/{experienceID}/delete` | — | `204`; its criteria, evidences and sessions go with it |

Changing dates keeps sessions inside the new range and rejects the change if a
session or a placed evidence would fall outside (`date_not_in_experience`).
Removing a competency that has criteria is rejected (`competency_has_criteria`);
the teacher deletes those criteria first. `idea_text` is not editable: it is
the seed the experience came from.

## Criteria

| Route | Body |
|---|---|
| `POST /experiences/{experienceID}/criteria` | `competency_id` (one of the experience's), `description`, `capability_ids` (≥1, of that competency), `performance_id` (a performance of that competency for the class's grade) |
| `PUT /criteria/{criterionID}` | any of `description`, `capability_ids`, `performance_id`; editing a proposal also accepts it |
| `POST /criteria/{criterionID}/accept` | — accepts a proposal unchanged |
| `POST /criteria/{criterionID}/delete` | — (existing route; also removes it from evidences) |

`performance_id` is required: criteria come only from the grade's
performances. Creating, editing and accepting answer with the criterion as the
experience read shows it (`201` / `200`). The edit and accept routes only
reach criteria of an experience; a global criterion is `404` there. A
criterion of an experience is authorized through its class (the delete route
included); a global one still through its area.

## Planned evidences

| Route | Body |
|---|---|
| `POST /experiences/{experienceID}/evidences` | `name`, `kind` (`produccion` \| `actuacion` \| `prueba_escrita`), `criterion_ids` (≥1, of this experience, any of its competencies), optional `session_date` |
| `PUT /evidences/{evidenceID}` | any of the above; `"session_date": null` takes it out of its session, leaving the key out keeps it; editing a proposal also accepts it |
| `POST /evidences/{evidenceID}/accept` | — |
| `POST /evidences/{evidenceID}/delete` | — |

`session_date` places the evidence in that date's session entry, which must
exist. Placement is one relation seen from both sides: setting an evidence's
`session_date` and setting a session's `planned_evidence_id` are the same
change, and the server keeps `planned_evidences.session_entry_id` and
`session_outline_entries.planned_evidence_id` in step. A session holds one
evidence, so placing an evidence in a session takes out the one that was there,
and moving an evidence empties its previous session. Deleting an evidence
empties its session; deleting a session leaves its evidence unplaced.

Creating, editing and accepting answer with the evidence (`201` / `200`).

## Session outline

One entry per class date of the experience.

| Route | Body |
|---|---|
| `PUT /experiences/{experienceID}/sessions/{date}` | `title`, optional `topics`, optional `planned_evidence_id`; creates or replaces that date's entry, and accepts it |
| `POST /experiences/{experienceID}/sessions/{date}/accept` | — |
| `POST /experiences/{experienceID}/sessions/{date}/delete` | — |

`date` must be a class date inside the experience and not a non-teaching day.
The `PUT` body is the entry's whole state: leaving `planned_evidence_id` out
empties the session. `PUT` and `accept` answer `200` with the entry; `delete`
answers `204`.

## Generate with Mawta (the planning agent, ticket 6)

These routes are served by the **planning agent**, the first agent of Mawta's
multi-agent system (`internal/agent/planning`, over the shared base
`internal/agent`). Each generation is one bounded call to Claude through the
Anthropic API: the server chooses the context (the experience, the loaded
curriculum, the class dates), the model must answer by filling a fixed JSON
schema, and the server validates the answer against the database before
storing anything.

Generations live in **`agent_generations`** (migration `00005`), a table
shared by every agent: `agent` says which one serves the request (`planning`
now; the session and conclusion agents later), `kind` what it generates. It is
tenant-scoped with RLS. The queued job (`agent.generate`) only carries the
generation id: the `jobs` table has no RLS and no result column, so it is
never exposed.

Each route creates a generation and returns `202` with it at once:
`{"id": "…", "kind": "criteria", "status": "pending"}`. A second request for
the same target while one is pending or running returns that one (one per
experience proposal per class, per competency for criteria, per experience
for evidences and sessions).

| Route | Body | What a completed generation did (`result`) |
|---|---|---|
| `POST /classes/{classID}/experience-proposals` | `term_id`, `idea_text`, optional `competency_ids` | `{"proposal": {"title", "situation_text", "competency_ids", "starts_on", "ends_on"}}`. **Not saved**: the app shows it for review, then calls `POST …/experiences`. The teacher's chosen competencies are kept as chosen. The dates always lie inside a free stretch of the term (no overlap, inside the term): if the model's do not, the server moves them to the nearest free stretch, keeping the length as far as it fits |
| `POST /experiences/{experienceID}/criteria/generate` | `competency_id` (one of the experience's) | `{"criteria_ids": [...]}`: pending criteria for that competency's capabilities without one. Each cites a performance of the class grade. With no gaps the model is not called and the list is empty |
| `POST /experiences/{experienceID}/evidences/generate` | — | `{"evidence_ids": [...]}`: pending evidences, each observing at least one criterion no evidence observed yet. Needs criteria first (`no_criteria`) |
| `POST /experiences/{experienceID}/sessions/generate` | — | `{"session_dates": [...]}`: pending entries on class dates without one, never replacing an existing entry; unplaced evidences may be placed in them |
| `GET /generations/{generationID}` | — | `{"id", "kind", "status", "result"?, "error"?}`; `result` only when completed, `error` (Spanish, for the teacher) only when failed |

Rules of the agent (`internal/agent/planning/prompts/`, versioned with each
generation):

- It only uses the loaded curriculum and the ids it was given; an item that
  cites a capability, performance, criterion, evidence or date that does not
  exist, or that fills no gap, is discarded.
- Everything it stores is pending (`proposed_by = "mawta"`,
  `accepted_at = null`) until the teacher accepts or edits it.
- It never suggests achievement levels and receives no student data. The
  teacher's idea is treated as content, not as instructions.
- An answer that cannot be used at all gets one repair attempt (the model is
  told what was wrong); after that the generation fails.

Lifecycle: `pending` → `running` → `completed` or `failed`. Transient model
failures (rate limits, overload, network) are retried by the queue, up to 3
attempts. A generation not finished **5 minutes** after it was requested reads
as `failed` ("tardó demasiado") and is never run late.

Without `ANTHROPIC_API_KEY` the four generation routes answer
`503 agent_unavailable`, so the app can offer manual creation only.
Configuration: `ANTHROPIC_API_KEY`, `PLANNING_AGENT_MODEL` (default
`claude-sonnet-5-5`), `AGENT_TIMEOUT` (default 90 s) and optional prices
(`AGENT_PRICE_INPUT_PER_MTOK`, `AGENT_PRICE_OUTPUT_PER_MTOK`,
`AGENT_PRICE_CACHE_READ_PER_MTOK`, `AGENT_PRICE_CACHE_WRITE_PER_MTOK`) to
estimate the cost recorded with each generation; without prices the tokens are
still recorded. Every model call also logs an `agent.usage` event with tokens
and cost, never with prompts or answers.

## Domain errors

| Code | Status | When |
|---|---|---|
| `experience_overlap` | 409 | The dates cross another experience of the class (drafts included) |
| `outside_term` | 422 | The experience starts before or ends after its term |
| `competency_not_in_subject` | 422 | A competency is not of the class's area |
| `competency_not_in_experience` | 422 | A criterion's competency is of the area but not one the experience works |
| `competency_has_criteria` | 409 | Removing a competency that still has criteria |
| `capability_not_in_competency` | 422 | A criterion capability belongs to another competency |
| `criterion_needs_capability` | 422 | A criterion with no capability |
| `performance_not_in_grade` | 422 | The performance is of another competency or grade |
| `criterion_other_experience` | 422 | An evidence uses a criterion of another experience |
| `date_not_in_experience` | 422 | A session or placed evidence date outside the experience, not a class date, or a non-teaching day; a `session_date` with no session entry; new experience dates that leave a session outside |
| `evidence_not_in_experience` | 422 | A session's `planned_evidence_id` is not an evidence of the experience |
| `session_date_taken` | 409 | Two requests created the same date's session entry at once |
| `experience_not_draft` | 409 | Confirming an experience that is already planned |
| `agent_unavailable` | 503 | No model is configured (`ANTHROPIC_API_KEY` unset); the app offers manual creation only |
| `competency_not_in_experience` | 422 | Generating criteria for a competency the experience does not work |
| `no_free_weeks`, `no_criteria`, `no_performances` | 200 (in the generation) | The agent cannot generate: no free stretch left in the term, no criteria to build evidences on, no performances loaded for the grade; the failed generation's `error` says so |
| `generation_failed` | 200 (in the generation) | Any generation that ends `failed`; `error` says why, in Spanish |

Malformed or missing input is `400`: `bad_request` (an id or date that does
not parse, an unknown evidence `kind`, `ends_on` before `starts_on`) or a
`missing_*` code (`missing_title`, `missing_idea`, `missing_competencies`,
`missing_description`, `missing_name`, `missing_criteria`). Messages are in
Spanish; the UI keys on the code.

## Out of scope

"No hubo clase" and re-planning, extending an experience, recording evidence,
term close (coverage, levels, descriptive conclusions), per-student
adjustments, the "Hoy" view, and the session-detail agent.
