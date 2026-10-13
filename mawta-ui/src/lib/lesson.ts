// Orchestration layer for the lesson screen: loads a session's roster from the
// API and owns every mutation. Each action updates the stores synchronously
// (instant UI), sends the API call in the background, and reverts the store
// with an error toast if the server rejects it — autosave, no submit button.

import { get } from 'svelte/store';
import { ApiError, fetchAudioBlob, list } from './api/client';
import type { RosterEntryDto, SessionRosterDto } from './api/dto';
import {
	createVoiceNote,
	discardVoiceNote,
	getSession,
	saveVoiceNote,
	startSession,
} from './api/endpoints/sessions';
import { parseDateOnly, splitDisplayName } from './api/mappers';
import { currentCourse, currentSession, entries, entryKey, notes, students } from './stores';
import { showError, showToast } from './toast';
import type { Entry, Note, Session, Student } from './types';

const SAVE_ERROR = 'No se pudo guardar — revisa tu conexión';

function toEntry(sessionId: string, dto: RosterEntryDto): { entry: Entry; noteList: Note[] } {
	const id = entryKey(sessionId, dto.student_id);
	const noteList: Note[] = list(dto.voice_notes)
		.filter((n) => n.status !== 'discarded')
		.map((n) => ({
			id: n.id,
			entryId: id,
			audioBlob: null,
			transcript: n.transcript,
			durationMs: n.duration_ms,
			status: n.status === 'saved' ? 'saved' : 'draft',
		}));
	return {
		entry: { id, sessionId, studentId: dto.student_id, notes: noteList },
		noteList,
	};
}

function applyRoster(sessionId: string, dto: SessionRosterDto): void {
	const h = dto.header;
	const session: Session = {
		id: h.session_id,
		classId: h.class_id,
		className: h.class_name,
		topic: h.topic,
		date: parseDateOnly(h.session_date),
		status: h.status,
	};
	currentSession.set(session);
	currentCourse.set({ id: h.class_id, name: h.class_name });

	const roster = list(dto.roster);
	const studentList: Student[] = roster.map((r) => {
		const { firstName, lastName } = splitDisplayName(r.name);
		return { id: r.student_id, courseId: h.class_id, firstName, lastName };
	});
	students.set(studentList);

	const entryMap = new Map<string, Entry>();
	const noteMap = new Map<string, Note[]>();
	for (const r of roster) {
		const { entry, noteList } = toEntry(sessionId, r);
		entryMap.set(entry.id, entry);
		if (noteList.length > 0) noteMap.set(entry.id, noteList);
	}
	entries.set(entryMap);
	notes.set(noteMap);
}

export async function loadSession(sessionId: string): Promise<void> {
	const roster = await getSession(sessionId);
	applyRoster(sessionId, roster);

	// Entering the lesson is "class begins" — promote a scheduled session.
	if (roster.header.status === 'scheduled') {
		startSession(sessionId)
			.then(() => currentSession.update(($s) => ($s ? { ...$s, status: 'in_progress' } : $s)))
			.catch(() => {
				// A parallel device may have started it already; harmless.
			});
	}
}

// --- voice notes ---

function setEntryNotes(entryId: string, noteList: Note[]): void {
	notes.update(($notes) => {
		if (noteList.length === 0) $notes.delete(entryId);
		else $notes.set(entryId, noteList);
		return new Map($notes);
	});
	entries.update(($entries) => {
		const entry = $entries.get(entryId);
		if (entry) $entries.set(entryId, { ...entry, notes: noteList });
		return new Map($entries);
	});
}

function replaceNote(entryId: string, noteId: string, next: Note | null): void {
	const current = get(notes).get(entryId) ?? [];
	const noteList =
		next === null
			? current.filter((n) => n.id !== noteId)
			: current.map((n) => (n.id === noteId ? next : n));
	setEntryNotes(entryId, noteList);
}

export async function addNote(studentId: string, blob: Blob, durationSec: number): Promise<void> {
	const session = get(currentSession);
	if (!session) return;
	const entryId = entryKey(session.id, studentId);
	if (!get(entries).has(entryId)) return;

	const durationMs = Math.round(durationSec * 1000);
	const note: Note = {
		id: `local-${Date.now()}`,
		entryId,
		studentId,
		audioBlob: blob,
		transcript: null,
		durationMs,
		status: 'draft',
		createdAt: new Date(),
	};
	setEntryNotes(entryId, [note, ...(get(notes).get(entryId) ?? [])]);
	await uploadNote(session.id, note);
}

// A refused upload keeps the note, with its audio, in the list as 'failed' so the
// teacher can retry it instead of recording again.
async function uploadNote(sessionId: string, note: Note): Promise<void> {
	if (!note.audioBlob || !note.studentId) return;
	try {
		const { id } = await createVoiceNote(
			sessionId,
			note.studentId,
			note.audioBlob,
			note.durationMs
		);
		// Saving is automatic: the note is taken through to "saved" right after the
		// create. If that second call fails, one silent retry follows, and if that also
		// fails the note stays "draft" server-side: still playable and deletable.
		replaceNote(note.entryId, note.id, { ...note, id, status: 'saved' });
		void saveVoiceNote(id).catch(() => void saveVoiceNote(id).catch(() => {}));
	} catch (err) {
		replaceNote(note.entryId, note.id, { ...note, status: 'failed' });
		// Validation rejections (over 1 min, empty/near-empty audio) carry a
		// specific server message worth showing instead of the generic one.
		showError(err instanceof ApiError ? err.message : SAVE_ERROR, {
			onRetry: () => void retryNote(note),
		});
	}
}

// Retries an upload the server refused, from the audio still held in memory.
export async function retryNote(note: Note): Promise<void> {
	const session = get(currentSession);
	if (!session) return;
	replaceNote(note.entryId, note.id, { ...note, status: 'draft' });
	await uploadNote(session.id, { ...note, status: 'draft' });
}

// Discard is final server-side; the confirm dialog already says so.
export function removeNote(note: Note): void {
	replaceNote(note.entryId, note.id, null);
	void discardVoiceNote(note.id).catch(() => {
		setEntryNotes(note.entryId, [note, ...(get(notes).get(note.entryId) ?? [])]);
		showToast(SAVE_ERROR);
	});
}

// Playback audio: local blob right after recording, fetched (and memoized on
// the note) for server-loaded notes.
export async function noteAudio(note: Note): Promise<Blob | null> {
	if (note.audioBlob) return note.audioBlob;
	try {
		const blob = await fetchAudioBlob(note.id);
		replaceNote(note.entryId, note.id, { ...note, audioBlob: blob });
		return blob;
	} catch {
		showToast('No se pudo cargar el audio');
		return null;
	}
}
