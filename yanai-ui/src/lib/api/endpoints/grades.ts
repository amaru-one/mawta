import { apiGet, apiSend } from '../client';
import type {
	PracticeScoreCreateDto,
	ScoreCorrectDto,
	ScoreCreateDto,
	StudentGradesDto,
} from '../dto';

export function getStudentGrades(
	classId: string,
	studentId: string,
	termId?: string
): Promise<StudentGradesDto> {
	const qs = termId ? `?term_id=${termId}` : '';
	return apiGet<StudentGradesDto>(`/classes/${classId}/students/${studentId}/grades${qs}`);
}

export function createScore(assessmentId: string, body: ScoreCreateDto): Promise<{ id: string }> {
	return apiSend<{ id: string }>('POST', `/assessments/${assessmentId}/scores`, body);
}

// Scores are append-only server-side: corrections supersede the old row.
// A second correct on the same id fails with 409 already_superseded.
export function correctScore(scoreId: string, body: ScoreCorrectDto): Promise<{ id: string }> {
	return apiSend<{ id: string }>('POST', `/scores/${scoreId}/correct`, body);
}

export function createPracticeScore(
	classId: string,
	studentId: string,
	body: PracticeScoreCreateDto
): Promise<{ id: string }> {
	return apiSend<{ id: string }>(
		'POST',
		`/classes/${classId}/students/${studentId}/practice-scores`,
		body
	);
}

export function deletePracticeScore(id: string): Promise<{ status: string }> {
	return apiSend<{ status: string }>('POST', `/practice-scores/${id}/delete`);
}

export function requestSummary(
	classId: string,
	studentId: string,
	termId?: string
): Promise<{ status: string }> {
	const qs = termId ? `?term_id=${termId}` : '';
	return apiSend<{ status: string }>(
		'POST',
		`/classes/${classId}/students/${studentId}/summary${qs}`
	);
}
