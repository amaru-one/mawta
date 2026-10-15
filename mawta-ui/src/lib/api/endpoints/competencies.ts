import { apiGet, apiSend } from '../client';
import type {
	AssertCompetencyLevelDto,
	CompetencyLevelsDto,
	ConclusionCreateDto,
	DiscardedVoiceNotesDto,
	GenerationDto,
	LatestConclusionGenerationDto,
} from '../dto';

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

// Writes a conclusión descriptiva.
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

// "✦ Generar con Mawta" for a conclusión descriptiva. Answers 202 with a
// generation to poll (waitForGeneration), or 422 level_required /
// insufficient_evidence (ApiError.body carries the numbers) at once.
export function generateConclusion(
	classId: string,
	studentId: string,
	competencyId: string,
	termId?: string
): Promise<GenerationDto> {
	return apiSend<GenerationDto>(
		'POST',
		`/classes/${classId}/students/${studentId}/conclusions/generate`,
		{ competency_id: competencyId, term_id: termId }
	);
}

// The latest proposal for this competency and term, so it survives a reload.
export function getLatestConclusionGeneration(
	classId: string,
	studentId: string,
	competencyId: string,
	termId?: string
): Promise<LatestConclusionGenerationDto> {
	const params = new URLSearchParams({ competency_id: competencyId });
	if (termId) params.set('term_id', termId);
	return apiGet<LatestConclusionGenerationDto>(
		`/classes/${classId}/students/${studentId}/conclusions/generation?${params}`
	);
}

// The student's voice notes the name sweep discarded, only when they are all
// the student has this term (otherwise an empty list).
export function getDiscardedVoiceNotes(
	classId: string,
	studentId: string,
	termId?: string
): Promise<DiscardedVoiceNotesDto> {
	const qs = termId ? `?term_id=${termId}` : '';
	return apiGet<DiscardedVoiceNotesDto>(
		`/classes/${classId}/students/${studentId}/voice-notes/discarded${qs}`
	);
}
