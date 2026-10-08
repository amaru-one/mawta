import { derived, writable, type Readable, type Writable } from 'svelte/store';
import type { Role } from './api/dto';
import type { AppNotification, Course, Entry, Note, Session, Student } from './types';

// Session state, populated by the root layout's GET /me probe on mount.
// 'unknown' is the state before that probe resolves — the layout renders no
// app chrome while it's unknown, so there is never a flash of app content
// before a redirect to /login. 'anonymous' means the probe 401'd (or the
// current route is /login itself, which is never probed).
export type SessionState =
	{ status: 'unknown' } | { status: 'anonymous' } | { status: 'authenticated'; role: Role };

export const session: Writable<SessionState> = writable({ status: 'unknown' });

export const currentCourse: Writable<Course | null> = writable(null);
export const currentSession: Writable<Session | null> = writable(null);
export const students: Writable<Student[]> = writable([]);
export const notifications: Writable<AppNotification[]> = writable([]);

// Signed-in teacher identity from GET /me, loaded once by the layout.
type TeacherIdentity = {
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
