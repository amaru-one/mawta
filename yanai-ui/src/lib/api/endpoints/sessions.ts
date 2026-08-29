import { apiGet, apiSend, apiUpload } from '../client';
import type {
	AttendancePutDto,
	AttendanceStatus,
	FlagTypeDto,
	ObservationPutDto,
	SessionRosterDto,
	SessionStatus,
	VoiceNoteStatus,
} from '../dto';

export function getSession(sessionId: string, q?: string): Promise<SessionRosterDto> {
	const qs = q ? `?q=${encodeURIComponent(q)}` : '';
	return apiGet<SessionRosterDto>(`/sessions/${sessionId}${qs}`);
}

export function startSession(sessionId: string): Promise<{ status: SessionStatus }> {
	return apiSend<{ status: SessionStatus }>('POST', `/sessions/${sessionId}/start`);
}

export function putAttendance(
	sessionId: string,
	studentId: string,
	body: AttendancePutDto
): Promise<{ status: AttendanceStatus }> {
	return apiSend<{ status: AttendanceStatus }>(
		'PUT',
		`/sessions/${sessionId}/attendance/${studentId}`,
		body
	);
}

export function markAllPresent(sessionId: string): Promise<{ marked: number }> {
	return apiSend<{ marked: number }>('POST', `/sessions/${sessionId}/attendance/mark-all-present`);
}

export function putObservation(
	sessionId: string,
	studentId: string,
	body: ObservationPutDto
): Promise<{ ok: boolean }> {
	return apiSend<{ ok: boolean }>('PUT', `/sessions/${sessionId}/observations/${studentId}`, body);
}

export function createVoiceNote(
	sessionId: string,
	studentId: string,
	audio: Blob,
	durationMs: number
): Promise<{ id: string }> {
	const form = new FormData();
	form.append('audio', audio, 'note.webm');
	form.append('duration_ms', String(durationMs));
	form.append('mime_type', audio.type || 'audio/webm');
	return apiUpload<{ id: string }>(
		`/sessions/${sessionId}/students/${studentId}/voice-notes`,
		form
	);
}

export function saveVoiceNote(voiceNoteId: string): Promise<{ status: VoiceNoteStatus }> {
	return apiSend<{ status: VoiceNoteStatus }>('POST', `/voice-notes/${voiceNoteId}/save`);
}

export function discardVoiceNote(voiceNoteId: string): Promise<{ status: VoiceNoteStatus }> {
	return apiSend<{ status: VoiceNoteStatus }>('POST', `/voice-notes/${voiceNoteId}/discard`);
}

// Requires the /api/v1/flag-types endpoint (added server-side in Phase 3).
export function getFlagTypes(): Promise<{ flag_types: FlagTypeDto[] | null }> {
	return apiGet<{ flag_types: FlagTypeDto[] | null }>('/flag-types');
}
