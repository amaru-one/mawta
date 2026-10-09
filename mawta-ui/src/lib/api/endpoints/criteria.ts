import { apiGet, apiSend } from '../client';
import type { ClassCriteriaDto, CriterionCreateDto } from '../dto';

// Every competencia of the class's área with the criterios the teacher has
// written for it — what evidence is read against, and what a piece of evidencia
// is tagged with when it is filed.
//
// A competencia with no criterios comes back with an empty list rather than
// being omitted: under RVM 094-2020 criterios are what evidence is judged
// against, so an empty one is what the teacher most needs to see.
export function getClassCriteria(classId: string): Promise<ClassCriteriaDto> {
	return apiGet<ClassCriteriaDto>(`/classes/${classId}/criteria`);
}

// The criterios "Añadir evidencia" offers: for every competencia of the class's
// área, the accepted criterios of the class's planned experiencias in the term
// (the current one when termId is omitted), each with its experiencia. Under
// RVM 094-2020 a criterio is written for a situation, so general criterios and
// drafts are not offered.
export function getEvidenceCriteria(classId: string, termId?: string): Promise<ClassCriteriaDto> {
	const qs = termId ? `?term_id=${encodeURIComponent(termId)}` : '';
	return apiGet<ClassCriteriaDto>(`/classes/${classId}/evidence-criteria${qs}`);
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

// Soft-deletes a criterio. Evidence already tagged with it keeps the tag — it
// is part of a student's history even once the teacher stops using the criterio.
export function deleteCriterion(criterionId: string): Promise<void> {
	return apiSend<void>('POST', `/criteria/${criterionId}/delete`);
}
