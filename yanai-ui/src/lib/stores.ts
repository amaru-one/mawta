import { derived, writable, type Readable, type Writable } from 'svelte/store';
import type { AppNotification, Course, Entry, Note, Session, Student } from './types';

export const currentCourse: Writable<Course | null> = writable(null);
export const currentSession: Writable<Session | null> = writable(null);
export const students: Writable<Student[]> = writable([]);
export const notifications: Writable<AppNotification[]> = writable([]);

// True once the SPA has made at least one client-side navigation, so a
// `history.back()` is guaranteed to land on another screen of this app rather
// than leaving it. False on a cold load or a refresh — a deep link has no
// in-app history behind it. Set by the root layout's afterNavigate.
export const canGoBack: Writable<boolean> = writable(false);

// Signed-in teacher identity from GET /me, loaded once by the layout.
export type TeacherIdentity = {
	initials: string;
	shortName: string;
	school: string;
};

export const teacher: Writable<TeacherIdentity | null> = writable(null);

// Whether the school runs its own weighted numeric system alongside the
// official MINEDU record (D.S. 009-2006-ED art. 37.4.f). Loaded once by the
// layout from GET /me. False hides every mark input and the internal grade
// card; it never changes how a nivel de logro is produced, which is the
// teacher's judgement of evidence against the criterios either way.
//
// Defaults to true so a screen rendered before /me resolves looks like the
// historical app rather than briefly hiding controls a school does use.
export const usesInternalGrading: Writable<boolean> = writable(true);

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
