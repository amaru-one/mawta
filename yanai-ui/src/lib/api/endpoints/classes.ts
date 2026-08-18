import { apiGet, apiSend } from '../client';
import type { AssessmentCreateDto, ClassDashboardDto, SessionListDto } from '../dto';

export function getClassDashboard(classId: string, termId?: string): Promise<ClassDashboardDto> {
	const qs = termId ? `?term_id=${termId}` : '';
	return apiGet<ClassDashboardDto>(`/classes/${classId}/dashboard${qs}`);
}

export function getClassSessions(
	classId: string,
	dir: 'upcoming' | 'past',
	limit?: number
): Promise<SessionListDto> {
	const qs = new URLSearchParams({ dir });
	if (limit !== undefined) qs.set('limit', String(limit));
	return apiGet<SessionListDto>(`/classes/${classId}/sessions?${qs}`);
}

export function createAssessment(classId: string, body: AssessmentCreateDto): Promise<{ id: string }> {
	return apiSend<{ id: string }>('POST', `/classes/${classId}/assessments`, body);
}
