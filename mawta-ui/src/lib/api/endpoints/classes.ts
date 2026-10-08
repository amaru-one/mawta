import { apiGet, apiSend } from '../client';
import type { AssessmentCreateDto, ClassDashboardDto } from '../dto';

export function getClassDashboard(classId: string, termId?: string): Promise<ClassDashboardDto> {
	const qs = termId ? `?term_id=${termId}` : '';
	return apiGet<ClassDashboardDto>(`/classes/${classId}/dashboard${qs}`);
}

// Files one piece of evidencia. `student_id` omitted creates a column for the
// whole class; set, the evidence belongs to that student alone.
export function createAssessment(
	classId: string,
	body: AssessmentCreateDto
): Promise<{ id: string }> {
	return apiSend<{ id: string }>('POST', `/classes/${classId}/assessments`, body);
}

// Soft-deletes a piece of evidence. Scores already recorded against it stay in
// the student's history, the same way a deleted criterio keeps its levels.
export function deleteAssessment(assessmentId: string): Promise<void> {
	return apiSend<void>('POST', `/assessments/${assessmentId}/delete`);
}
