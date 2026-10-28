# Descriptive conclusions with Mawta — API contract

Mawta proposes the *conclusión descriptiva* of one student in one competency
and term. The teacher reviews, edits and saves it through the existing
conclusions endpoint; Mawta never saves or finalises it on their behalf.

One agent takes part (`src/agent/conclusions`):

| Agent | Kind | When it runs | What it reads | What it writes |
|---|---|---|---|---|
| `conclusions` | `conclusion` | When the teacher asks | Level, requirement, competency + capabilities, the term's evidences (score, feedback, criteria), the transcribed voice notes, earlier terms | `agent_generations.result` (the proposal) |

It is one bounded model call over data the server chose, answered by
filling a fixed schema that the server validates (one repair round on an
invalid answer). Generations live in `agent_generations`, polled with
`GET /generations/{id}`.

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

Before queueing, the server checks the minimum:

- `503 agent_unavailable` — `CONCLUSIONS_AGENT_MODEL` is empty, or its provider lacks what it
  needs (an address for Ollama, a key for OpenRouter).
- `422 level_required` — no level asserted yet.
- `422 insufficient_evidence` — fewer graded evidences than the minimum. The
  body carries the numbers:

  ```json
  {
    "error": { "code": "insufficient_evidence", "message": "Hay poca evidencia…" },
    "evidence": {
      "graded_count": 1,
      "minimum": 2,
      "usable_voice_notes": 0
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
  "body": "Explica… Aún confunde… Se le recomienda…",
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
    { "code": "voice_notes_pending", "count": 1 }
  ]
}
```

Warnings are frozen at generation time, so they describe what the agent
actually read:

| Code | Meaning | UI |
|---|---|---|
| `voice_notes_pending` | Notes still being transcribed | Count only |
| `no_voice_notes` | The student has no notes this term | "Less precise" |
| `evidence_single_kind` | Every graded evidence is one kind (`kind`: `produccion` or `actuacion`); the CNEB asks for varied evidence | Note, the proposal still runs |
| `evidence_single_experience` | Every graded evidence comes from one learning experience; the CNEB asks for diverse situations | Note, the proposal still runs |

The two evidence codes appear only from the minimum of graded evidence on, and
only about graded evidence. Evidence the teacher added by hand has no
experience, so it never proves a single experience on its own.

`body` is the conclusion as SIAGIE receives it: one paragraph with progress,
difficulties, the justification or supports when the norm asks for them, and
recommendations. SIAGIE accepts 10 to 350 characters, so the agent writes
within that range from the start (`src/domain.py`).

What the server enforces on the model's answer (otherwise one repair round,
then the generation fails):

- every progress and difficulty cites at least one evidence or voice note it
  was given (`E1…`, `N1…` references, mapped back to ids);
- at least one progress, one difficulty and one recommendation: the norm asks
  every conclusion to state all three (RM 281-2016, CNEB VII; RVM 094-2020,
  5.1.1.3 p.7). Only at level AD, when the material shows no difficulty, the
  difficulty is the fixed sentence "No presenta dificultades significativas en
  esta competencia." (`NoDifficultiesAD`); at any other level that sentence is
  rejected;
- `body` is at most 350 characters (counted in characters, not bytes);
- `no_progress_justification` for `consecutive_c`, `supports_provided` for
  `inclusion_support`;
- no replacement token and no name of a student on the roster anywhere in the
  text (accent-insensitive, as a capitalised word). Voice notes and feedback
  reach the model with the names the teacher said or wrote, so this check is
  what keeps every name out of the conclusion.

## `GET /classes/{classID}/students/{studentID}/conclusions/generation?competency_id=&term_id=`

The latest conclusion generation for that scope, so a proposal survives a
reload: `200 {"generation": <generation> | null}`.

## Saving: `POST /classes/{classID}/students/{studentID}/conclusions`

Unchanged, plus an optional `generation_id`: the proposal the teacher started
from. It must be a completed `conclusions` generation for the same student,
competency and term (`422 generation_mismatch` otherwise) and is stored in
`descriptive_conclusions.generation_id`. The text is the teacher's
(`authored_by_id`); the link makes it traceable to what the agent read. When
that generation used at least one voice note (`used_voice_note_ids`), the
server sets `descriptive_conclusions.generated_from_voice_notes`; the client
never sends it.

`body` is normalized (NFC, one paragraph, whitespace collapsed) and must be 10
to 350 characters, **draft or final**: `422 conclusion_too_short` or
`422 conclusion_too_long`, with the count in the message. The check
`dc_body_siagie` enforces the same in the database.

## Privacy

- Mawta runs on open models chosen per agent (chat-director D004): on the
  school's own server with Ollama, or through OpenRouter. With a local model
  nothing leaves the school; with OpenRouter, the material below goes to that
  provider and belongs in the school's data-processing agreement.
- The conclusions agent reads the voice-note transcripts as transcribed, names
  included, and score feedback as the teacher wrote it. The output guard keeps
  every name out of the proposal.
- `agent_generations.input` carries ids only. `agent_generations` is declared
  as a table with minors' data.

## Configuration

| Variable | Default |
|---|---|
| `CONCLUSIONS_AGENT_MODEL` | empty (agent unavailable); `provider:model`, e.g. `ollama:gemma4:12b-it-qat` or `openrouter:openai/gpt-oss-120b` |
| `OLLAMA_URL`, `OLLAMA_API_KEY` | `http://127.0.0.1:11434/v1`, empty |
| `OPENROUTER_URL`, `OPENROUTER_API_KEY` | `https://openrouter.ai/api/v1`, empty |
| `AGENT_TIMEOUT`, `AGENT_DEADLINE` | `90s` per model call, `5m` per generation; raise both for a slow local model |
| `CONCLUSIONS_AGENT_PRICE_{INPUT,OUTPUT,CACHE_READ,CACHE_WRITE}_PER_MTOK` | 0 (cost unknown) |
