import { apiGet } from '../client';
import type { ClassStudentsDto, StudentEvidenceDto } from '../dto';

// The class roster with each student's nivel de logro in one competencia and
// the number of pieces of evidencia behind it.
//
// `competencyId` is optional: a class whose área has no competencias configured
// still has a roster, and the students with no levels are a more useful answer
// than an error.
export function getClassStudents(
	classId: string,
	competencyId?: string,
	termId?: string
): Promise<ClassStudentsDto> {
	const params = new URLSearchParams();
	if (competencyId) params.set('competency_id', competencyId);
	if (termId) params.set('term_id', termId);
	const qs = params.toString() ? `?${params}` : '';
	return apiGet<ClassStudentsDto>(`/classes/${classId}/students${qs}`);
}

// The period's evidencia for one student, narrowed to one competencia through
// the criterio tags each piece carries.
//
// This is the material a teacher reads before asserting the level. Nothing in
// it is aggregated and nothing suggests a level — the norm makes that a
// judgement, not an average (RVM 094-2020, 5.1.1.3 p.2-3).
export function getStudentEvidence(
	classId: string,
	studentId: string,
	competencyId?: string,
	termId?: string
): Promise<StudentEvidenceDto> {
	const params = new URLSearchParams();
	if (competencyId) params.set('competency_id', competencyId);
	if (termId) params.set('term_id', termId);
	const qs = params.toString() ? `?${params}` : '';
	return apiGet<StudentEvidenceDto>(`/classes/${classId}/students/${studentId}/evidence${qs}`);
}
