import { derived, writable, type Readable, type Writable } from 'svelte/store';
import type { Assessment, Course, Entry, Note, Session, Student } from './types';

export const currentCourse: Writable<Course | null> = writable(null);
export const currentSession: Writable<Session | null> = writable(null);
export const students: Writable<Student[]> = writable([]);

// Entries keyed by `${sessionId}:${studentId}`.
export const entries: Writable<Map<string, Entry>> = writable(new Map());

// Notes keyed by entryId, newest first.
export const notes: Writable<Map<string, Note[]>> = writable(new Map());

export const assessments: Writable<Assessment[]> = writable([]);

export const entryKey = (sessionId: string, studentId: string): string =>
	`${sessionId}:${studentId}`;

// "18/28 entered" — students with at least one field filled.
export const enteredCount: Readable<number> = derived(entries, ($entries) => {
	let n = 0;
	for (const e of $entries.values()) {
		if (e.attendance !== null || e.participation !== null || e.notes.length > 0) n++;
	}
	return n;
});
