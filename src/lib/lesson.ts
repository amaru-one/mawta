// Orchestration layer: bootstraps today's session and owns every mutation.
// Each action updates the stores synchronously (instant UI) and persists to
// IndexedDB in the background — autosave, no submit button.

import { get, writable, type Writable } from 'svelte/store';
import * as db from './db';
import { seedIfEmpty } from './seed';
import {
	assessments,
	currentCourse,
	currentSession,
	entries,
	entryKey,
	notes,
	students
} from './stores';
import type {
	Assessment,
	Attendance,
	Block,
	Entry,
	Note,
	NoteTag,
	Participation,
	Session,
	SessionMode
} from './types';

// UI mode is tracked separately from session.blocks: a teacher can pick an
// assessment mode before choosing which assessment, and switching modes must
// never discard the other block's data.
export const sessionMode: Writable<SessionMode> = writable('lesson');

let lessonBlock: Block = { kind: 'lesson', topic: 'fractions' };
let assessmentBlock: Extract<Block, { kind: 'assessment' }> | null = null;

// Note durations are runtime-only metadata (the persisted model stores just
// the blob); recorded live, recovered from audio metadata after a reload.
export const noteDurations: Writable<Map<string, number>> = writable(new Map());

const uid = (): string =>
	typeof crypto !== 'undefined' && 'randomUUID' in crypto
		? crypto.randomUUID()
		: `id-${Date.now()}-${Math.random().toString(36).slice(2)}`;

function isToday(d: Date): boolean {
	const now = new Date();
	const date = new Date(d);
	return (
		date.getFullYear() === now.getFullYear() &&
		date.getMonth() === now.getMonth() &&
		date.getDate() === now.getDate()
	);
}

function modeFromBlocks(blocks: Block[]): SessionMode {
	const hasLesson = blocks.some((b) => b.kind === 'lesson');
	const hasAssessment = blocks.some((b) => b.kind === 'assessment');
	if (hasLesson && hasAssessment) return 'lesson+assessment';
	if (hasAssessment) return 'assessment';
	return 'lesson';
}

export async function loadToday(): Promise<void> {
	const courseId = await seedIfEmpty();
	const [courses, courseStudents, courseAssessments, courseSessions] = await Promise.all([
		db.getCourses(),
		db.getStudents(courseId),
		db.getAssessments(courseId),
		db.getSessions(courseId)
	]);

	const course = courses.find((c) => c.id === courseId) ?? null;
	currentCourse.set(course);
	courseStudents.sort((a, b) =>
		`${a.firstName} ${a.lastName}`.localeCompare(`${b.firstName} ${b.lastName}`)
	);
	students.set(courseStudents);
	assessments.set(courseAssessments);

	let session = courseSessions.find((s) => isToday(s.date)) ?? null;
	if (!session) {
		// Timetable default for Math 8B: 10:00–12:00, plan is a lesson on fractions.
		session = {
			id: uid(),
			courseId,
			date: new Date(),
			startTime: '10:00',
			endTime: '12:00',
			blocks: [{ kind: 'lesson', topic: 'fractions' }]
		};
		await db.saveSession(session);
	}

	for (const block of session.blocks) {
		if (block.kind === 'lesson') lessonBlock = block;
		else assessmentBlock = block;
	}
	sessionMode.set(modeFromBlocks(session.blocks));
	currentSession.set(session);

	const savedEntries = await db.getEntries(session.id);
	const entryMap = new Map<string, Entry>();
	for (const student of courseStudents) {
		const saved = savedEntries.find((e) => e.studentId === student.id);
		const entry: Entry =
			saved ?? {
				id: uid(),
				sessionId: session.id,
				studentId: student.id,
				attendance: null,
				participation: null,
				tookAssessment: null,
				notes: []
			};
		entryMap.set(entryKey(session.id, student.id), entry);
	}

	const noteMap = new Map<string, Note[]>();
	await Promise.all(
		[...entryMap.values()].map(async (entry) => {
			const entryNotes = await db.getNotes(entry.id);
			entryNotes.sort((a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime());
			entry.notes = entryNotes;
			if (entryNotes.length > 0) noteMap.set(entry.id, entryNotes);
		})
	);

	notes.set(noteMap);
	entries.set(entryMap);
}

function updateEntry(studentId: string, patch: Partial<Entry>): void {
	const session = get(currentSession);
	if (!session) return;
	const key = entryKey(session.id, studentId);
	entries.update(($entries) => {
		const entry = $entries.get(key);
		if (!entry) return $entries;
		const updated = { ...entry, ...patch };
		$entries.set(key, updated);
		void db.saveEntry(updated);
		return new Map($entries);
	});
}

export async function setAttendance(studentId: string, value: Attendance | null): Promise<void> {
	updateEntry(studentId, { attendance: value });
}

export async function setParticipation(
	studentId: string,
	value: Participation | null
): Promise<void> {
	updateEntry(studentId, { participation: value });
}

export async function setTookAssessment(studentId: string, value: boolean): Promise<void> {
	updateEntry(studentId, { tookAssessment: value });
}

// --- Set-all (one undoable action) ---

export interface SetAllUndo {
	restore: () => void;
}

function snapshotAndApply(apply: (entry: Entry) => Entry, visibleIds?: Set<string>): SetAllUndo {
	const before = new Map<string, Entry>();
	entries.update(($entries) => {
		for (const [key, entry] of $entries) {
			if (visibleIds && !visibleIds.has(entry.studentId)) continue;
			before.set(key, entry);
			const updated = apply(entry);
			if (updated !== entry) {
				$entries.set(key, updated);
				void db.saveEntry(updated);
			}
		}
		return new Map($entries);
	});
	return {
		restore: () => {
			entries.update(($entries) => {
				for (const [key, entry] of before) {
					$entries.set(key, entry);
					void db.saveEntry(entry);
				}
				return new Map($entries);
			});
		}
	};
}

export function setAllPresent(visibleIds?: Set<string>): SetAllUndo {
	return snapshotAndApply(
		(e) => (e.attendance === 'present' ? e : { ...e, attendance: 'present' }),
		visibleIds
	);
}

// Marks everyone not absent as "good" (2). Absent students don't participate.
export function setAllParticipated(visibleIds?: Set<string>): SetAllUndo {
	return snapshotAndApply(
		(e) => (e.attendance === 'absent' || e.participation === 2 ? e : { ...e, participation: 2 }),
		visibleIds
	);
}

// --- Voice notes ---

export async function addNote(studentId: string, blob: Blob, durationSec: number): Promise<Note | null> {
	const session = get(currentSession);
	if (!session) return null;
	const key = entryKey(session.id, studentId);
	const entry = get(entries).get(key);
	if (!entry) return null;

	const note: Note = {
		id: uid(),
		entryId: entry.id,
		audioBlob: blob,
		transcript: null,
		createdAt: new Date()
	};

	noteDurations.update(($d) => {
		$d.set(note.id, durationSec);
		return new Map($d);
	});
	notes.update(($notes) => {
		const list = $notes.get(entry.id) ?? [];
		$notes.set(entry.id, [note, ...list]);
		return new Map($notes);
	});
	updateEntry(studentId, { notes: [note, ...entry.notes] });
	void db.saveNote(note);
	return note;
}

export function removeNote(note: Note): { restore: () => void } {
	notes.update(($notes) => {
		const list = ($notes.get(note.entryId) ?? []).filter((n) => n.id !== note.id);
		if (list.length === 0) $notes.delete(note.entryId);
		else $notes.set(note.entryId, list);
		return new Map($notes);
	});
	syncEntryNotes(note.entryId);
	void db.deleteNote(note.id);
	return {
		restore: () => {
			notes.update(($notes) => {
				const list = [note, ...($notes.get(note.entryId) ?? [])];
				list.sort((a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime());
				$notes.set(note.entryId, list);
				return new Map($notes);
			});
			syncEntryNotes(note.entryId);
			void db.saveNote(note);
		}
	};
}

export function tagNote(note: Note, tag: NoteTag | undefined): void {
	const updated: Note = { ...note, tag };
	notes.update(($notes) => {
		const list = ($notes.get(note.entryId) ?? []).map((n) => (n.id === note.id ? updated : n));
		$notes.set(note.entryId, list);
		return new Map($notes);
	});
	syncEntryNotes(note.entryId);
	void db.saveNote(updated);
}

// Keeps entry.notes mirroring the notes store for the given entry.
function syncEntryNotes(entryId: string): void {
	const session = get(currentSession);
	if (!session) return;
	const $notes = get(notes);
	entries.update(($entries) => {
		for (const [key, entry] of $entries) {
			if (entry.id === entryId) {
				$entries.set(key, { ...entry, notes: $notes.get(entryId) ?? [] });
			}
		}
		return new Map($entries);
	});
}

// --- Mode & assessment ---

function persistBlocks(blocks: Block[]): void {
	const session = get(currentSession);
	if (!session) return;
	const updated: Session = { ...session, blocks };
	currentSession.set(updated);
	void db.saveSession(updated);
}

export function setMode(mode: SessionMode): void {
	sessionMode.set(mode);
	const blocks: Block[] = [];
	if (mode === 'lesson' || mode === 'lesson+assessment') blocks.push(lessonBlock);
	if ((mode === 'assessment' || mode === 'lesson+assessment') && assessmentBlock) {
		blocks.push(assessmentBlock);
	}
	persistBlocks(blocks);
}

export function chooseAssessment(assessmentId: string): void {
	assessmentBlock = { kind: 'assessment', assessmentId };
	setMode(get(sessionMode));
}

export async function createAssessment(
	name: string,
	type: Assessment['type'],
	maxScore: number
): Promise<void> {
	const course = get(currentCourse);
	if (!course) return;
	const assessment: Assessment = {
		id: uid(),
		courseId: course.id,
		name,
		type,
		maxScore,
		status: 'planned'
	};
	assessments.update(($a) => [...$a, assessment]);
	await db.saveAssessment(assessment);
	chooseAssessment(assessment.id);
}
