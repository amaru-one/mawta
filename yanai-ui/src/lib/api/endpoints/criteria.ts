import { apiGet, apiSend } from '../client';
import type {
	AssessmentCriteriaGridDto,
	AssertCriterionLevelDto,
	ClassCriteriaDto,
	CriterionCreateDto,
} from '../dto';

// Every competencia of the class's área with the criterios the teacher has
// written for it. Pass studentId to get that student's evidencia × criterio row
// per criterio — the grid weighed before asserting the competency level.
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

// One cell of the evidencia × criterio grid: what this student showed against
// one criterio, on one piece of evidence. `assessment_id` is required — a
// criterio is the ruler, never the thing being marked (RVM 094-2020, 5.1.1.3
// p.3), and the server rejects a body without it as
// `criterion_level_needs_evidence`.
//
// Evidence, not the official record: nothing rolls these up into the competency
// level. Append-only server-side, like competency levels.
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

// One piece of evidence across its whole roster: criterios as columns, students
// as rows, the levels already recorded as cells. The marking view — one
// criterio at a time down thirty scripts, rather than thirty screens.
//
// No mark comes back from here on purpose. The school's numeric system is the
// other reading of the same evidence and lives on the student's screen; a /20
// box beside these pickers would put a number in the teacher's eye at the exact
// moment they are meant to be judging against a criterio.
export function getAssessmentCriteriaGrid(
	assessmentId: string
): Promise<AssessmentCriteriaGridDto> {
	return apiGet<AssessmentCriteriaGridDto>(`/assessments/${assessmentId}/criteria-grid`);
}
