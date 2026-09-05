## Purpose
**Alumnos** — the class seen as a list of people, scoped to one competencia. It reports where each
student stands and it is the way into their screen. It deliberately **does not evaluate**: no picker,
no marking mode, no bulk action.

## Contents
- `+page.svelte` — a `.titlerow` (30px "Alumnos" + a search icon that folds a `.search` field in),
  a mono sub-line (`{clase} · N alumnos`), the `CompetencyIndex`, the selected competencia's name at
  19px, a mono `N DE M CON NIVEL` counter, and the list: level badge, name, trailing `chevron-right`.
  Each row links to `students/{studentId}?name=&course=`.
- `[studentId]/` — the student's screen, where evaluating happens (see its SPEC.md).

## Inputs / Outputs
Route param `courseId`. Reads `getClassDashboard` (the class name), `getClassCriteria` (the
competencias for the index) and `getClassStudents` (the roster with levels and evidence counts, one
request, refetched when the competencia changes). **No mutations.**

## Conventions & Constraints
- **The list never evaluates.** Marking from a roster either overflows the row or asks the teacher to
  judge thirty students with none of the evidence in front of them. The decision lives one screen in,
  under the evidence it is read from.
- **Everything on screen is scoped to the competencia in the index**, because a nivel de logro only
  means something against one. The competencia is stated once, at the top, rather than repeated per
  row.
- On this screen the index's third state means **"closed for the whole class"** — every student has a
  level. On the student's screen the same glyph means "this student has a level". The component
  renders three states; each screen decides what they mean.
- **A student with no level shows a dash, never a C** (RVM 048-2024, 5.1.2.2). The dashed square is
  the same 26px as `LevelBadge` so the column stays aligned.
- The level leads the row rather than trailing it: it is what the teacher scans down, and a badge on
  the right would have to be found past a ragged name column.
- Search filters the loaded rows on screen; it never refetches.

## Open Questions
- The index can only mark the competencia being looked at as "closed for the whole class": only that
  one's levels are loaded. Marking the others would mean reading every competencia's levels for every
  student, which is a much bigger query than the glyph is worth.

## Change Log
- 2026-09-04: Moved onto `GET /classes/{classID}/students`. The four gaps this screen shipped with in
  the morning all closed at once: the roster no longer comes out of a session (so a class with no
  sessions has a list), the levels are one request instead of one per student, «N evidencias» is
  rendered, and the name arrives as `Apellidos, Nombres` the way a Peruvian register lists it.
  Switching competencia refetches and dims the list rather than blanking it — the names do not change.
- 2026-09-04: Created, as the first of the two screens the área gained. See the parent
  `routes/SPEC.md` for the model change this screen belongs to.
