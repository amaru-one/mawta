## Purpose
One student, one competencia: **read, then decide**. The evidence of the period with its values, and
under it the single judgement that reaches the official record — the nivel de logro of the
competencia (RVM 094-2020, 5.1.1.3 p.2-3). This is the screen where a teacher evaluates.

## Contents
- `+page.svelte` — name at 34px over the shared rule, mono uppercase sub-line, `CompetencyIndex` over this student's competencias,
  the competencia's name at 15px/600, then two sections: **EVIDENCIAS DEL PERIODO** (one hairline-ruled
  card per piece: title + a mono kind·date line, the criterios it is tagged with as read-only text,
  the control its scale calls for, and a "No entregó" row with a marker square) and **NIVEL DE LOGRO** (`LevelSelector`, then the
  conclusión descriptiva block: textarea, "incluye recomendaciones", *Guardar borrador* / *Marcar como
  final*).

## Inputs / Outputs
Route params `courseId`, `studentId`. `?name=`, `?course=` and `?comp=` carry the student name, the
class name and the selected competencia, since no endpoint returns any of them — the same convention
`grades/[studentId]` uses for the first two. Reads `getStudentCompetencies` + `getClassCriteria`
(`Promise.all`), then `getStudentEvidence` for the selected competencia — the server does the
narrowing, so the screen never holds work it is not showing, and changing competencia is a fresh read.
Mutations: `createScore`/`correctScore`, `assertCompetencyLevel`, `upsertConclusion`. Reads
`usesInternalGrading` from `lib/stores.ts`.

## Conventions & Constraints
- **The selected competencia survives a remount, via `?comp=`.** `selected` is local `$state`, and
  SvelteKit remounts this route's component on every navigation, back navigation included — without
  the URL, `load()` had no way to tell "never chosen yet" from "chosen, then the page was torn down",
  and always fell back to the first competencia. `selectCompetency()` writes the choice into `?comp=`
  with `goto(..., {replaceState: true})` — no new history entry, so a back navigation lands on the URL
  that already names the competencia being read, and a hard reload opens on it too. `students/`
  propagates its own `selected` into `?comp=` on the link to each row, so arriving here from the list
  already opens on the competencia that list was showing.
- **The order of the screen is the order of the judgement.** Evidence first, decision second, with a
  heading and extra space between them. Reversing them would put the teacher's own past answer above
  the material it is supposed to rest on.
- **There is no accordion, and it was not swapped for another gesture — the state was deleted.**
  Every evidence is open with its control in place: nothing to expand, nothing to collapse, nothing
  left half-open between visits. That is only affordable with a control compact enough to sit on
  every card at once, which is why the mark is a `ScoreRuler` and not a field or a keypad.
- **Line controls inform; the boxed control decides.** The rulers are lines with no enclosure;
  `LevelSelector` is the only element on the screen inside a 1px stroke. That hierarchy is what
  separates "I valued this work" from "I decided the official record", and it is load-bearing — do
  not box the evidence controls or unbox the level.
- **Nothing computes the level.** No suggestion, no average, no roll-up, and the copy under the
  selector says so. A criterio is rendered as text only: it says what to look at in the work, it is
  not itself graded.
- **Evidence is attributed to a competencia through its criterio tags**, server-side. A piece belongs
  here when it is tagged with at least one criterio of the selected competencia; evidence tagged with
  none belongs to no competencia and appears nowhere here — it is still listed on `grades/[studentId]`.
- **The control is chosen by the evidence, not by the screen.** `value_scale` `numeric` draws a
  `ScoreRuler` over `max_score`, `ordinal` draws a `LevelScale`, `none` draws no control and says so
  in a line — a named gap rather than one that looks broken. `usesInternalGrading` false also
  suppresses the ruler, with its own sentence, since a school with no numeric system has nothing for a
  mark to mean.
- **A letter on a piece of evidencia is not a nivel de logro.** `LevelScale` and `LevelSelector` show
  the same four letters and must stay visually distinct for that reason: the first is a line control
  on a card, the second is the one boxed control on the screen.
- **"No entregó" writes `status: 'not_submitted'` with a null value; untoggling it writes `graded`
  back with whatever mark was there** — from `lastValue`, a `Map<assessmentId, {rawValue, level}>` kept
  outside `evidence` and populated the instant before marking, never from `markOf`/`letterOf` at the
  moment of untoggling. By then those already read the *cleared* attempt (marking not_submitted nulls
  the value server-side), so deriving from them sent `status: 'graded'` with both `raw_value` and
  `level` null — which the DB's own `scores_value_matches_status` check rejects outright, so the write
  failed silently and the row stayed stuck on "no entregó". `lastValue` is session-only: it does not
  survive a reload, and it has nothing to offer for a piece that was never graded before being marked.
  For both of those, and as a general shortcut, **the ruler/letters are never disabled by "no
  entregó"** — picking a value there calls `writeScore(..., 'graded', v, ...)` directly regardless of
  the mark, which is the one path guaranteed to work no matter what `lastValue` does or doesn't hold.
  It is a row with a marker square, never a pill.
- Saves are per tap and patch local state instead of refetching, keyed per assessment so one slow
  write never freezes the card beside it — the idiom the criterios and evidence screens already use.
- The conclusión descriptiva is **always open**, not behind a disclosure: for a student at level C or
  with inclusion support it is mandatory, and hiding it behind a tap is how it goes unwritten. A
  `final` conclusión without recommendations is blocked client-side, mirroring the server's 422.

## Open Questions
- `CompetencyLevelDto` does not carry `includes_recommendations`, so the checkbox always starts
  unticked even when a conclusión already exists — re-saving an existing final one means re-ticking
  it. Fixing it properly means adding the field to the DTO.
- The sub-line names the class but not the periodo: no read on this screen returns a term label, only
  `term_id`. Inventing "Bimestre III" would be a lie, so it is omitted.
