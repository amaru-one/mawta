import { apiGet, apiSend } from '../client';
import type { AssertCriterionLevelDto, ClassCriteriaDto, CriterionCreateDto } from '../dto';

// Every competencia of the class's área with the criterios the teacher has
// written for it. Pass studentId to get that student's level per criterio for
// the period — the evidence weighed before asserting the competency level.
//
// A competencia with no criterios comes back with an empty list rather than
// being omitted: under RVM 094-2020 criterios are what evidence is judged
// against, so an empty one is what the teacher most needs to see.
export function getClassCriteria(
	classId: string,
	studentId?: string,
	termId?: string
): Promise<ClassCriteriaDto> {
	const params = new URLSearchParams();
	if (studentId) params.set('student_id', studentId);
	if (termId) params.set('term_id', termId);
	const qs = params.toString() ? `?${params}` : '';
	return apiGet<ClassCriteriaDto>(`/classes/${classId}/criteria${qs}`);
}

// The teacher writes a criterio for one competencia. The text is theirs; the
// server rejects a blank description and a competencia outside the class's área.
export function createCriterion(
	classId: string,
	competencyId: string,
	body: CriterionCreateDto
): Promise<{ id: string }> {
	return apiSend<{ id: string }>(
		'POST',
		`/classes/${classId}/competencies/${competencyId}/criteria`,
		body
	);
}

// Soft-deletes a criterio. Levels already recorded against it stay — they are
// part of a student's history even once the teacher stops using the criterio.
export function deleteCriterion(criterionId: string): Promise<void> {
	return apiSend<void>('POST', `/criteria/${criterionId}/delete`);
}

// The teacher's level for one criterio over the whole period. Evidence, not
// the official record: nothing rolls these up into the competency level.
// Append-only server-side, like competency levels.
export function assertCriterionLevel(
	classId: string,
	studentId: string,
	body: AssertCriterionLevelDto
): Promise<{ id: string; level: string }> {
	return apiSend<{ id: string; level: string }>(
		'POST',
		`/classes/${classId}/students/${studentId}/criterion-levels`,
		body
	);
}
