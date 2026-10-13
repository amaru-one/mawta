# Descriptive conclusions with Mawta — API contract

Mawta proposes the *conclusión descriptiva* of one student in one competency
and term. The teacher reviews, edits and saves it through the existing
conclusions endpoint; Mawta never saves or finalises it on their behalf.

Two agents take part (`internal/agent`):

| Agent | Kind | When it runs | What it reads | What it writes |
|---|---|---|---|---|
| `redaction` | `voice_note` | After a voice note is transcribed | The transcript, the assigned student's names, the section roster's names | `voice_notes.transcript_redacted`, `attribution_status`, one `voice_note_redactions` row per replacement |
| `conclusions` | `conclusion` | When the teacher asks | Level, requirement, competency + capabilities, the term's evidences (score, feedback, criteria), redacted voice notes, earlier terms | `agent_generations.result` (the proposal) |

Both are one bounded model call over data the server chose, answered by
filling a fixed schema that the server validates (one repair round on an
invalid answer). Generations live in `agent_generations`, polled with
`GET /generations/{id}`.

## Name sweep (redaction)

Teachers speak freely: they name the student, classmates, relatives and other
teachers, and speech-to-text misspells names. The sweep is done **only by a
model**, because recognising "Yon" as Jhon or "el chato" as a person needs
context.

- The model gets the transcript, the assigned student (key `S0`) and the
  classmates of the section on the note's date (keys `S1…Sn`).
- It answers `{fragments: [{text, refers_to, student_key}], unreadable}` where
  `refers_to` is `assigned_student`, `classmate` or `other_person`. It never
  rewrites the transcript.
- The server checks that every fragment occurs in the transcript (whole word,
  case-insensitive), computes the offsets, and replaces every occurrence:
  `[ESTUDIANTE]`, `[COMPAÑERO_n]` (numbered per note by first appearance),
  `[PERSONA]`. Longer fragments win over shorter ones inside them.
- One `voice_note_redactions` row per replacement: original text, rune
  offsets in `transcript`, replacement, `refers_to`, matched student,
  `method = 'model'`, and the generation (model + prompt version). The
  original `transcript` is kept, so every decision can be reviewed with SQL:

  ```sql
  select vn.transcript, vn.transcript_redacted, r.original_text, r.replacement,
         r.refers_to, r.matched_student_id, g.model, g.prompt_version
    from voice_notes vn
    join voice_note_redactions r on r.voice_note_id = vn.id and r.superseded_at is null
    join agent_generations g on g.id = r.generation_id
   where vn.id = $1
   order by r.start_offset;
  ```

- Attribution (`voice_notes.attribution_status`):

  | The sweep found… | Status |
  |---|---|
  | The assigned student, with or without others | `ok` |
  | Nobody, or only other people | `ok` |
  | Only classmates, never the assigned student | `discarded` / `mentions_other_student` |
  | Noise, no meaning (or a blank transcript) | `discarded` / `unreadable` |

  There is no quarantine: a discarded note is simply left out of conclusions.
  The teacher only sees discarded notes in the worst case: **every** voice
  note of the student in the term was discarded. Otherwise they are only
  counted (`voice_notes_discarded`).

### `GET /classes/{classID}/students/{studentID}/voice-notes/discarded?term_id=`

The student's discarded notes in the term (`id`, `recorded_at`,
`duration_ms`, original `transcript`, `discard_reason`), **only in the worst
case**; `{"voice_notes": []}` otherwise. The UI loads it when a proposal
carries the warning `all_voice_notes_discarded`.

- The sweep is queued by the transcription job when `ANTHROPIC_API_KEY` is
  set. Notes left `pending` (recorded before the sweep existed, or while no key
  was configured) are queued again when a conclusion is requested.

### `POST /voice-notes/{voiceNoteID}/reassign`

```json
{ "student_id": "<uuid>" }
```

Moves the note to another student on the class roster, clears its redacted
transcript, supersedes its redaction rows and sweeps it again around the new
student. The resulting status is `reassigned` (the teacher's decision stands)
unless the note is unreadable. Event `voice_note.reassigned`.

`200 {id, student_id, attribution_status: "pending"}`. `422 same_student` when
the note already belongs to that student; `403` when the student is not on the
roster.

### `POST /voice-notes/{voiceNoteID}/confirm`

The teacher keeps a note discarded for `mentions_other_student`. Event
`voice_note.confirmed`. `200 {id, student_id, attribution_status: "confirmed"}`.
`422 not_confirmable` for any other note (pending, unreadable, already usable).

## Minimum to propose a conclusion

- A level asserted by the teacher for that competency and term
  (`competency_term_levels`). The conclusion explains that level; the agent
  never suggests or contests it.
- At least **2** distinct evidences with a live `graded` score, read against
  a criterion of the competency in the term (`conclusions.MinGradedEvidences`).
- Voice notes never count toward the minimum. Without any usable note the
  proposal is still made, with the warning `no_voice_notes`.

## `POST /classes/{classID}/students/{studentID}/conclusions/generate`

```json
{ "competency_id": "<uuid>", "term_id": "<uuid, optional: defaults to the class's current term>" }
```

Authorization: the teacher teaches the class, the student is on its roster,
the competency belongs to the class's área.

Before queueing, the server sweeps any pending notes and checks the minimum:

- `503 agent_unavailable` — no model configured.
- `422 level_required` — no level asserted yet.
- `422 insufficient_evidence` — fewer graded evidences than the minimum. The
  body carries the numbers and, in the worst case (every note discarded),
  those notes, so the teacher can reassign or confirm them:

  ```json
  {
    "error": { "code": "insufficient_evidence", "message": "Hay poca evidencia…" },
    "evidence": {
      "graded_count": 1,
      "minimum": 2,
      "usable_voice_notes": 0,
      "discarded_voice_notes": [
        { "id": "…", "recorded_at": "…", "duration_ms": 4200,
          "transcript": "original transcript", "discard_reason": "mentions_other_student" }
      ]
    }
  }
  ```

Otherwise `202` with a generation (`kind: "conclusion"`), one in flight per
student, competency and term (`target_key
conclusions:student:<s>:comp:<c>:term:<t>`). Poll `GET /generations/{id}`.
A generation can still fail with `level_required`, `insufficient_evidence` or
`level_changed` (the level changed while Mawta wrote).

### Result of a completed generation

```json
{
  "body": "Explica…\n\nAún confunde…\n\nSe le recomienda…",
  "level": "B",
  "requirement": "level_b",
  "progress":        [{ "text": "…", "evidence_ids": ["…"], "voice_note_ids": ["…"] }],
  "difficulties":    [{ "text": "…", "evidence_ids": ["…"], "voice_note_ids": [] }],
  "recommendations": [{ "text": "…", "evidence_ids": [], "voice_note_ids": [] }],
  "no_progress_justification": "only for consecutive_c",
  "supports_provided": "only for inclusion_support",
  "used_voice_note_ids": ["…"],
  "unused_voice_notes": [{ "voice_note_id": "…", "reason": "…" }],
  "warnings": [
    { "code": "voice_notes_discarded", "count": 2 },
    { "code": "voice_notes_pending", "count": 1 }
  ]
}
```

Warnings are frozen at generation time, so they describe what the agent
actually read:

| Code | Meaning | UI |
|---|---|---|
| `voice_notes_discarded` | Some notes were discarded, others used | Count only |
| `all_voice_notes_discarded` | Every note was discarded (worst case) | Shows the notes to move or confirm |
| `voice_notes_pending` | Notes still transcribing or waiting for the sweep | Count only |
| `no_voice_notes` | The student has no notes this term | "Less precise" |
| `evidence_single_kind` | Every graded evidence is one kind (`kind`: `produccion` or `actuacion`); the CNEB asks for varied evidence | Note, the proposal still runs |
| `evidence_single_experience` | Every graded evidence comes from one learning experience; the CNEB asks for diverse situations | Note, the proposal still runs |

The two evidence codes appear only from the minimum of graded evidence on, and
only about graded evidence. Evidence the teacher added by hand has no
experience, so it never proves a single experience on its own.

`body` is progress, difficulties, the justification or supports
when the norm asks for them, and recommendations, one paragraph each.

What the server enforces on the model's answer (otherwise one repair round,
then the generation fails):

- every progress and difficulty cites at least one evidence or voice note it
  was given (`E1…`, `N1…` references, mapped back to ids);
- at least one recommendation (RVM 094-2020, 5.1.1.3 p.7);
- `no_progress_justification` for `consecutive_c`, `supports_provided` for
  `inclusion_support`;
- no replacement token and no name of a student on the roster anywhere in the
  text (accent-insensitive, as a capitalised word). This is a last net, not a
  redaction method.

## `GET /classes/{classID}/students/{studentID}/conclusions/generation?competency_id=&term_id=`

The latest conclusion generation for that scope, so a proposal survives a
reload: `200 {"generation": <generation> | null}`.

## Saving: `POST /classes/{classID}/students/{studentID}/conclusions`

Unchanged, plus an optional `generation_id`: the proposal the teacher started
from. It must be a completed `conclusions` generation for the same student,
competency and term (`422 generation_mismatch` otherwise) and is stored in
`descriptive_conclusions.generation_id`. The text is the teacher's
(`authored_by_id`); the link makes it traceable to what the agent read.

## Privacy

- Audio already goes to the speech-to-text provider. The sweep sends the
  transcript and the section's names to the model provider: recognising a
  misspelled name needs them. Both belong in the school's data-processing
  agreement.
- The conclusions agent only reads `transcript_redacted`, and the student is
  `[ESTUDIANTE]` in its prompt. Score feedback is the teacher's free text and
  is **not** swept; the output guard is what keeps a name written there out
  of the proposal.
- `agent_generations.input` carries ids only. `voice_note_redactions` and
  `agent_generations` are declared as tables with minors' data.

## Configuration

| Variable | Default |
|---|---|
| `REDACTION_AGENT_MODEL` | `claude-haiku-5-5` |
| `REDACTION_AGENT_PRICE_{INPUT,OUTPUT,CACHE_READ,CACHE_WRITE}_PER_MTOK` | 0 (cost unknown) |
| `CONCLUSIONS_AGENT_MODEL` | `claude-sonnet-5-5` |
| `CONCLUSIONS_AGENT_PRICE_{INPUT,OUTPUT,CACHE_READ,CACHE_WRITE}_PER_MTOK` | 0 (cost unknown) |
