import { apiGet, apiSend, apiUpload } from '../client';
import type { SessionRosterDto, SessionStatus, VoiceNoteStatus } from '../dto';

export function getSession(sessionId: string, q?: string): Promise<SessionRosterDto> {
	const qs = q ? `?q=${encodeURIComponent(q)}` : '';
	return apiGet<SessionRosterDto>(`/sessions/${sessionId}${qs}`);
}

export function startSession(sessionId: string): Promise<{ status: SessionStatus }> {
	return apiSend<{ status: SessionStatus }>('POST', `/sessions/${sessionId}/start`);
}

// The two attendance routes (PUT .../attendance/{studentID} and
// POST .../attendance/mark-all-present) are live server-side and deliberately
// have no wrapper here — see this folder's SPEC.md.

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
