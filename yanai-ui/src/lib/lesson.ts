// Orchestration layer for the lesson screen: loads a session's roster from the
// API and owns every mutation. Each action updates the stores synchronously
// (instant UI), sends the API call in the background, and reverts the store
// with an error toast if the server rejects it — autosave, no submit button.

import { get } from 'svelte/store';
import { ApiError, fetchAudioBlob, list } from './api/client';
import type { AttendanceStatus, RosterEntryDto, SessionRosterDto } from './api/dto';
import {
	createVoiceNote,
	discardVoiceNote,
	getFlagTypes,
	getSession,
	markAllPresent as apiMarkAllPresent,
	putAttendance,
	putObservation,
	saveVoiceNote,
	startSession,
} from './api/endpoints/sessions';
import { parseDateOnly, splitDisplayName } from './api/mappers';
import { currentCourse, currentSession, entries, entryKey, notes, students } from './stores';
import { showToast } from './toast';
import type { Attendance, Entry, Note, Session, Student } from './types';

const SAVE_ERROR = 'No se pudo guardar — revisa tu conexión';

// The UI keeps attendance binary; the server's late/excused/justified statuses
// collapse into the nearest bucket and are overwritten if the teacher toggles.
function toAttendance(status: AttendanceStatus | null): Attendance | null {
	if (status === null) return null;
	return status === 'present' || status === 'late' ? 'present' : 'absent';
}

// FlagButton is boolean; the server wants flag-type UUIDs. Flagging uses the
// tenant's first flag type; unflagging clears the whole set.
let defaultFlagTypeId: string | null = null;

async function ensureFlagTypes(): Promise<void> {
	if (defaultFlagTypeId !== null) return;
	try {
		const flagTypes = list((await getFlagTypes()).flag_types);
		defaultFlagTypeId = flagTypes[0]?.id ?? null;
	} catch {
		// Flagging degrades gracefully until the next load.
	}
}

function toEntry(sessionId: string, dto: RosterEntryDto): { entry: Entry; noteList: Note[] } {
	const id = entryKey(sessionId, dto.student_id);
	const flagTypeIds = list(dto.flags).map((f) => f.id);
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
		entry: {
			id,
			sessionId,
			studentId: dto.student_id,
			attendance: toAttendance(dto.attendance_status),
			flagged: flagTypeIds.length > 0,
			flagTypeIds,
			observationNote: dto.observation_note,
			notes: noteList,
		},
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
		sectionAverageCode: h.section_average_code,
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
	const [roster] = await Promise.all([getSession(sessionId), ensureFlagTypes()]);
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

// --- entry mutations (optimistic, revert on server rejection) ---

function patchEntry(studentId: string, patch: Partial<Entry>): Entry | null {
	const session = get(currentSession);
	if (!session) return null;
	const key = entryKey(session.id, studentId);
	let previous: Entry | null = null;
	entries.update(($entries) => {
		const entry = $entries.get(key);
		if (!entry) return $entries;
		previous = entry;
		$entries.set(key, { ...entry, ...patch });
		return new Map($entries);
	});
	return previous;
}

function restoreEntry(previous: Entry): void {
	entries.update(($entries) => {
		$entries.set(previous.id, previous);
		return new Map($entries);
	});
}

function runMutation(previous: Entry | null, call: Promise<unknown>): void {
	void call.catch((err: unknown) => {
		if (previous) restoreEntry(previous);
		showToast(err instanceof ApiError && err.hint ? err.hint : SAVE_ERROR);
	});
}

export function setAttendance(studentId: string, value: Attendance): void {
	const session = get(currentSession);
	if (!session) return;
	const previous = patchEntry(studentId, { attendance: value });
	runMutation(previous, putAttendance(session.id, studentId, { status: value }));
}

// Observation PUTs replace the whole observation, so every field the entry
// already holds must ride along or it silently clears server-side.
function putEntryObservation(entry: Entry): Promise<unknown> {
	return putObservation(entry.sessionId, entry.studentId, {
		note: entry.observationNote,
		flag_type_ids: entry.flagTypeIds,
	});
}

export function setFlag(studentId: string, value: boolean): void {
	const session = get(currentSession);
	if (!session) return;
	if (value && defaultFlagTypeId === null) {
		showToast(SAVE_ERROR);
		return;
	}
	const flagTypeIds = value && defaultFlagTypeId !== null ? [defaultFlagTypeId] : [];
	const previous = patchEntry(studentId, { flagged: value, flagTypeIds });
	const updated = get(entries).get(entryKey(session.id, studentId));
	if (!updated) return;
	runMutation(previous, putEntryObservation(updated));
}

// --- mark all present ---

export function anyUnmarked(): boolean {
	for (const entry of get(entries).values()) {
		if (entry.attendance === null) return true;
	}
	return false;
}

// Attendance is a register: the server upserts but never unsets, so there is
// no "clear all" and no undo — matching the API's append-only philosophy.
export async function markAllPresent(): Promise<number> {
	const session = get(currentSession);
	if (!session) return 0;

	const before = new Map<string, Entry>();
	entries.update(($entries) => {
		for (const [key, entry] of $entries) {
			if (entry.attendance === null) {
				before.set(key, entry);
				$entries.set(key, { ...entry, attendance: 'present' });
			}
		}
		return new Map($entries);
	});

	try {
		const { marked } = await apiMarkAllPresent(session.id);
		return marked;
	} catch {
		entries.update(($entries) => {
			for (const [key, entry] of before) $entries.set(key, entry);
			return new Map($entries);
		});
		showToast(SAVE_ERROR);
		return 0;
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
	const localId = `local-${Date.now()}`;
	const note: Note = {
		id: localId,
		entryId,
		audioBlob: blob,
		transcript: null,
		durationMs,
		status: 'draft',
		createdAt: new Date(),
	};
	setEntryNotes(entryId, [note, ...(get(notes).get(entryId) ?? [])]);

	try {
		const { id } = await createVoiceNote(session.id, studentId, blob, durationMs);
		replaceNote(entryId, localId, { ...note, id });
	} catch (err) {
		replaceNote(entryId, localId, null);
		// Validation rejections (over 1 min, empty/near-empty audio) carry a
		// specific server message worth showing instead of the generic one.
		showToast(err instanceof ApiError ? err.message : SAVE_ERROR);
	}
}

export function saveNote(note: Note): void {
	replaceNote(note.entryId, note.id, { ...note, status: 'saved' });
	void saveVoiceNote(note.id).catch(() => {
		replaceNote(note.entryId, note.id, note);
		showToast(SAVE_ERROR);
	});
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
