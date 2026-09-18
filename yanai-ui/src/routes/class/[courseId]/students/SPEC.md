## Purpose
**Alumnos** — the class seen as a list of people, scoped to one competencia. It reports where each
student stands and it is the way into their screen. It deliberately **does not evaluate**: no picker,
no marking mode, no bulk action.

## Contents
- `+page.svelte` — a `.titlerow` (34px "Alumnos" over the shared rule, + a search icon that folds a `.search` field in),
  a mono sub-line (`{clase} · N alumnos`), the `CompetencyIndex`, the selected competencia's name at
  15px/600, a mono `N DE M CON NIVEL` counter, and the list: level badge, name, trailing `chevron-right`.
  Each row links to `students/{studentId}?name=&course=&comp=` — `comp` is this screen's own selected
  competencia, so the student screen opens already scoped to it.
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
- **The choice survives a remount, via `?comp=`.** `selected` is local `$state`, and SvelteKit remounts
  this route on every navigation, including a back navigation from a student's screen — without the
  URL, `load()` could not tell "never chosen" from "chosen, then torn down" and always fell back to the
  first competencia. `selectCompetency()` writes it with `goto(..., {replaceState: true})` (no new
  history entry), so back-navigating here lands on the URL that already names it, and a hard reload
  opens on it too.
- On this screen the index's third state means **"closed for the whole class"** — every student has a
  level. On the student's screen the same glyph means "this student has a level". The component
  renders three states; each screen decides what they mean.
- **A student with no level shows a dash, never a C** (RVM 048-2024, 5.1.2.2). The dashed disc is
  the same 26px as `LevelBadge` so the column stays aligned.
- The level leads the row rather than trailing it: it is what the teacher scans down, and a badge on
  the right would have to be found past a ragged name column.
- Search filters the loaded rows on screen; it never refetches.

## Open Questions
- The index can only mark the competencia being looked at as "closed for the whole class": only that
  one's levels are loaded. Marking the others would mean reading every competencia's levels for every
  student, which is a much bigger query than the glyph is worth.
