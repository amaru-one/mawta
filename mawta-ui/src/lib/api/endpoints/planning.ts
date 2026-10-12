import { apiGet, apiSend } from '../client';
import type {
	CalendarDto,
	ClassPlanDto,
	CreateCriterionBody,
	CreateEvidenceBody,
	CreateExperienceBody,
	CurriculumDto,
	ExperienceCriterionDto,
	ExperienceDto,
	ExperienceProposalBody,
	GenerationDto,
	PlannedEvidenceDto,
	SessionOutlineDto,
	UpdateCriterionBody,
	UpdateEvidenceBody,
	UpdateExperienceBody,
	UpdateSessionBody,
} from '../dto';

// "Tu trimestre": the term that contains today (or `termId`), its non-teaching
// days, the class's experiences and the competencies with their computed
// status. The plan screen's whole read.
export function getClassPlan(classId: string, termId?: string): Promise<ClassPlanDto> {
	const qs = termId ? `?term_id=${termId}` : '';
	return apiGet<ClassPlanDto>(`/classes/${classId}/plan${qs}`);
}

// The class's area competencies with their capabilities, the cycle standard
// (the main source of criteria) and the grade's desempeños (optional support).
export function getClassCurriculum(classId: string): Promise<CurriculumDto> {
	return apiGet<CurriculumDto>(`/classes/${classId}/curriculum`);
}

// Class dates and non-teaching days in a range at most one term long, for
// choosing experience dates and laying out sessions.
export function getCalendar(classId: string, from: string, to: string): Promise<CalendarDto> {
	return apiGet<CalendarDto>(`/classes/${classId}/calendar?from=${from}&to=${to}`);
}

// The whole experience: competencies, criteria, evidences, session outline,
// class dates and warnings. One read for the review, criteria, evidences,
// sessions and summary screens.
export function getExperience(experienceId: string): Promise<ExperienceDto> {
	return apiGet<ExperienceDto>(`/experiences/${experienceId}`);
}

// Creates the experience as a draft on the first step. Every later step writes
// to the database, so nothing is lost if the phone closes halfway.
export function createExperience(
	classId: string,
	body: CreateExperienceBody
): Promise<ExperienceDto> {
	return apiSend<ExperienceDto>('POST', `/classes/${classId}/experiences`, body);
}

// Edits the draft. Changing dates keeps sessions inside the new range and is
// rejected when a session or a placed evidence would fall outside; removing a
// competencia that still has criteria is rejected too.
export function updateExperience(
	experienceId: string,
	body: UpdateExperienceBody
): Promise<ExperienceDto> {
	return apiSend<ExperienceDto>('PUT', `/experiences/${experienceId}`, body);
}

// "Revisar y guardar": the draft becomes planificada. Only a draft can be
// confirmed; the warnings it still carries come back with it.
export function confirmExperience(experienceId: string): Promise<ExperienceDto> {
	return apiSend<ExperienceDto>('POST', `/experiences/${experienceId}/confirm`);
}

// Soft-deletes the experience; its criteria, evidences and sessions go with it.
export function deleteExperience(experienceId: string): Promise<void> {
	return apiSend<void>('POST', `/experiences/${experienceId}/delete`);
}

// Writes a criterio inside the experience: one of its competencies, a
// description, at least one capability of that competencia and a desempeño of
// that competencia for the class's grade.
export function createCriterion(
	experienceId: string,
	body: CreateCriterionBody
): Promise<ExperienceCriterionDto> {
	return apiSend<ExperienceCriterionDto>('POST', `/experiences/${experienceId}/criteria`, body);
}

// Edits a criterio; editing a proposal also accepts it.
export function updateCriterion(
	criterionId: string,
	body: UpdateCriterionBody
): Promise<ExperienceCriterionDto> {
	return apiSend<ExperienceCriterionDto>('PUT', `/criteria/${criterionId}`, body);
}

// Accepts a proposal unchanged — the teacher decides, Mawta only proposes.
export function acceptCriterion(criterionId: string): Promise<ExperienceCriterionDto> {
	return apiSend<ExperienceCriterionDto>('POST', `/criteria/${criterionId}/accept`);
}

// Soft-deletes a criterio; evidences tagged with it lose the tag.
export function deleteCriterion(criterionId: string): Promise<void> {
	return apiSend<void>('POST', `/criteria/${criterionId}/delete`);
}

// Plans a piece of evidencia over the experience's criteria, optionally placed
// in that class date's session entry.
export function createEvidence(
	experienceId: string,
	body: CreateEvidenceBody
): Promise<PlannedEvidenceDto> {
	return apiSend<PlannedEvidenceDto>('POST', `/experiences/${experienceId}/evidences`, body);
}

// Edits a planned evidencia; editing a proposal also accepts it. Placement is
// one relation seen from both sides, so setting `session_date` here and
// setting a session's `planned_evidence_id` are the same change.
export function updateEvidence(
	evidenceId: string,
	body: UpdateEvidenceBody
): Promise<PlannedEvidenceDto> {
	return apiSend<PlannedEvidenceDto>('PUT', `/evidences/${evidenceId}`, body);
}

// Accepts a proposed evidencia unchanged.
export function acceptEvidence(evidenceId: string): Promise<PlannedEvidenceDto> {
	return apiSend<PlannedEvidenceDto>('POST', `/evidences/${evidenceId}/accept`);
}

// Soft-deletes a planned evidencia; its session entry keeps existing without it.
export function deleteEvidence(evidenceId: string): Promise<void> {
	return apiSend<void>('POST', `/evidences/${evidenceId}/delete`);
}

// Creates or replaces that class date's session entry, and accepts it. The
// date must be a class date inside the experience and not a non-teaching day.
export function updateSession(
	experienceId: string,
	date: string,
	body: UpdateSessionBody
): Promise<SessionOutlineDto> {
	return apiSend<SessionOutlineDto>('PUT', `/experiences/${experienceId}/sessions/${date}`, body);
}

// Accepts a proposed session entry unchanged.
export function acceptSession(experienceId: string, date: string): Promise<SessionOutlineDto> {
	return apiSend<SessionOutlineDto>('POST', `/experiences/${experienceId}/sessions/${date}/accept`);
}

// Deletes that date's session entry; a placed evidencia stays, unplaced.
export function deleteSession(experienceId: string, date: string): Promise<void> {
	return apiSend<void>('POST', `/experiences/${experienceId}/sessions/${date}/delete`);
}

// "Tengo una idea": starts a generation that proposes a whole experience from
// the teacher's idea. The proposal is NOT saved — the app shows it for review
// and the teacher creates the experience from it.
export function proposeExperience(
	classId: string,
	body: ExperienceProposalBody
): Promise<GenerationDto> {
	return apiSend<GenerationDto>('POST', `/classes/${classId}/experience-proposals`, body);
}

// "Generar con Mawta" for criteria: pending criteria for that competencia's
// capabilities without one. Only gaps are filled, never existing rows.
export function generateCriteria(
	experienceId: string,
	competencyId: string
): Promise<GenerationDto> {
	return apiSend<GenerationDto>('POST', `/experiences/${experienceId}/criteria/generate`, {
		competency_id: competencyId,
	});
}

// "Generar con Mawta" for evidences: pending evidences over the experience's
// criteria.
export function generateEvidences(experienceId: string): Promise<GenerationDto> {
	return apiSend<GenerationDto>('POST', `/experiences/${experienceId}/evidences/generate`);
}

// "Generar con Mawta" for the session outline: pending entries on the
// experience's class dates without one.
export function generateSessions(experienceId: string): Promise<GenerationDto> {
	return apiSend<GenerationDto>('POST', `/experiences/${experienceId}/sessions/generate`);
}

// Polls a generation. It starts pending and the completed result lists what it
// inserted (or the proposal, for experience-proposals).
export function getGeneration(generationId: string): Promise<GenerationDto> {
	return apiGet<GenerationDto>(`/generations/${generationId}`);
}
