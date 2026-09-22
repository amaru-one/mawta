## Purpose
Alumnos: the class as a list of people, scoped to one competencia. It reports where each student stands and links into their screen; it records nothing.

## Contents
- `+page.svelte` — `TopBar back="/class/{courseId}" useHistory`, a `.titlerow` carrying "Alumnos" over the shared rule beside a search toggle, a `{className} · N alumnos` sub-line, the `CompetencyIndex`, the selected competencia's name at 15px/600, a mono `{withLevel} DE {N} CON NIVEL` counter, the list, and a closing line: "El nivel de logro lo pones tú, leyendo las evidencias del periodo. Ninguna evidencia lo calcula."
  - A row is a `LevelBadge` (or a dashed disc of the same 26px when `level` is null, titled "Sin nivel"), the name, an `evidenceLabel` of `Sin evidencias` / `1 evidencia` / `N evidencias`, and a trailing `chevron-right`. It links to `students/{studentId}?name=&course=&comp=`, so the student screen opens on the competencia this list is showing.
- `[studentId]/` — the student's screen, where evaluating happens (see its SPEC.md).

## Inputs / Outputs
Route param `courseId`. `?comp=` carries the selected competencia, read on load and written by `selectCompetency()` with `goto('?' + params, { replaceState: true, keepFocus: true, noScroll: true })`. Reads `getClassDashboard` (for the class name) and `getClassCriteria` (for the index) in one `Promise.all`, then `getClassStudents(courseId, selected)`, refetched by an `$effect` whenever the competencia changes. No mutations.

## Conventions & Constraints
- The list reports and navigates; the decision lives one screen in, under the evidence it is read from.
- Everything on screen is scoped to the competencia in the index, which is stated once at the top rather than repeated per row.
- The selected competencia survives a remount through `?comp=`: `selected` is local `$state` and SvelteKit remounts the route on every navigation, so the URL is what distinguishes "never chosen" from "chosen, then torn down". `replaceState` keeps it out of the history stack, and a hard reload opens on it.
- The index's items are the área competencias numbered 1..n and the transversales labelled by their code with the `TRANS-` prefix stripped. `hasLevel` is set only for the selected competencia, and only when every loaded row has a non-null level — on this screen it means "closed for the whole class".
- A student with no level shows a dash rather than a C.
- The level leads the row; the chevron trails it.
- Search folds an input in from the title-row magnifier, focused through an `{@attach focusHere}` attachment, and filters the loaded rows on `full_name` client-side without refetching. Closing it clears the query.
- A failed refetch on a competencia switch leaves the rows on screen; the next switch or a reload retries. The `switching` flag drives a CSS class on the list while a refetch is in flight.
- Empty states: "Esta clase no tiene alumnos." with a blank query, "Ningún alumno coincide." otherwise. The error state is "No se pudo cargar la lista." over a `Reintentar` button.

## Open Questions
- The index can mark only the competencia being looked at as closed for the whole class, since only that one's levels are loaded. Marking the others would mean reading every competencia's levels for every student.
