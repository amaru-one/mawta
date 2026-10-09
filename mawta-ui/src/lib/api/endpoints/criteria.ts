import { apiGet } from '../client';
import type { ClassCriteriaDto } from '../dto';

// Every competencia of the class's área with its general criterios (the ones
// written before the planning flow, outside any experiencia). The student
// screens read it for the list of competencias; a new evidence takes its
// criterios from getEvidenceCriteria instead.
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
