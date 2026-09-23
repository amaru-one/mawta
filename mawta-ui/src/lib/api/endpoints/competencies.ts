import { apiGet, apiSend } from '../client';
import type { AssertCompetencyLevelDto, CompetencyLevelsDto, ConclusionCreateDto } from '../dto';

// The niveles de logro a teacher has asserted for one student in one class and
// period, and whether a conclusión descriptiva is mandatory. There is no
// suggested level: the norm makes this the teacher's judgement, not a number
// the system arrives at first.
export function getStudentCompetencies(
	classId: string,
	studentId: string,
	termId?: string
): Promise<CompetencyLevelsDto> {
	const qs = termId ? `?term_id=${termId}` : '';
	return apiGet<CompetencyLevelsDto>(`/classes/${classId}/students/${studentId}/competencies${qs}`);
}

// Records the official nivel de logro: a teacher's judgement over the period's
// evidence against the criterios (RVM 094-2020, 5.1.1.3 p.2-3), never derived
// from anything. Append-only server-side — re-asserting supersedes the
// previous row rather than editing it.
export function assertCompetencyLevel(
	classId: string,
	studentId: string,
	body: AssertCompetencyLevelDto
): Promise<{ id: string; level: string }> {
	return apiSend<{ id: string; level: string }>(
		'POST',
		`/classes/${classId}/students/${studentId}/competency-levels`,
		body
	);
}

// Writes a conclusión descriptiva. A 'final' one without
// includes_recommendations is rejected with 422 missing_recommendations.
export function upsertConclusion(
	classId: string,
	studentId: string,
	body: ConclusionCreateDto
): Promise<{ id: string; status: string }> {
	return apiSend<{ id: string; status: string }>(
		'POST',
		`/classes/${classId}/students/${studentId}/conclusions`,
		body
	);
}
