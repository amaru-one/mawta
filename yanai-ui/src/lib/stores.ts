import { derived, writable, type Readable, type Writable } from 'svelte/store';
import type { AppNotification, Course, Entry, Note, Session, Student } from './types';

export const currentCourse: Writable<Course | null> = writable(null);
export const currentSession: Writable<Session | null> = writable(null);
export const students: Writable<Student[]> = writable([]);
export const notifications: Writable<AppNotification[]> = writable([]);

// Signed-in teacher identity from GET /me, loaded once by the layout.
export type TeacherIdentity = {
	initials: string;
	shortName: string;
	school: string;
};

export const teacher: Writable<TeacherIdentity | null> = writable(null);

export const unreadNotificationCount: Readable<number> = derived(
	notifications,
	($notifications) => $notifications.filter((n) => !n.read).length
);

// Entries keyed by `${sessionId}:${studentId}`.
export const entries: Writable<Map<string, Entry>> = writable(new Map());

// Notes keyed by entryId, newest first.
export const notes: Writable<Map<string, Note[]>> = writable(new Map());

export const entryKey = (sessionId: string, studentId: string): string =>
	`${sessionId}:${studentId}`;
