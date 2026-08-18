// App-side data model. Wire shapes live in $lib/api/dto; the mappers in
// $lib/api translate between the two.

import type { IconName } from './icons';

// --- View models built from the API ---

export type CourseStatus = 'live' | 'pending' | 'idle';

// One card on the Home screen, built from GET /home.
export type HomeCourse = {
	id: string;
	name: string;
	icon: IconName;
	schedule: string[];
	status: CourseStatus;
	bucket: 'today' | 'week';
	// Today's session, when one exists — links straight into the lesson screen.
	sessionId: string | null;
};

export type Course = {
	id: string;
	name: string; // "Math 8B"
};

export type Student = {
	id: string;
	courseId: string;
	firstName: string;
	lastName: string;
	avatar?: string; // initials or color
};

// A session is one block of time in one class, served by GET /sessions/{id}.
export type Session = {
	id: string;
	classId: string;
	className: string;
	topic: string | null;
	date: Date;
	status: 'scheduled' | 'in_progress' | 'completed' | 'cancelled' | 'rescheduled';
	// MINEDU level code (AD/A/B/C) averaged across the section, when computed.
	sectionAverageCode: string | null;
};

export type Attendance = 'present' | 'absent';

// 0=not rated, 1-3=star rating.
export type Participation = 0 | 1 | 2 | 3;

// One entry per student per session, built from the session roster.
export type Entry = {
	// Natural key `${sessionId}:${studentId}` — the server has no entry id.
	id: string;
	sessionId: string;
	studentId: string;
	attendance: Attendance | null;
	participation: Participation | null;
	// Teacher-raised behavior marker for this session; `flagTypeIds` carries the
	// server's flag-type UUIDs behind the boolean, and observation PUTs are an
	// authoritative set, so both must ride along on every mutation.
	flagged: boolean;
	flagTypeIds: string[];
	observationNote: string | null;
	// Grade standing from the server (recomputed asynchronously).
	levelCode: string | null;
	previousLevelCode: string | null;
	trend: 'up' | 'down' | 'flat' | null;
	notes: Note[];
};

export type Note = {
	id: string;
	entryId: string;
	// Present right after recording; server-loaded notes fetch audio on demand.
	audioBlob: Blob | null;
	transcript: string | null;
	durationMs: number;
	status: 'draft' | 'saved';
	createdAt?: Date;
};

// 'risk' and 'tip' come from the assistant; 'reminder' is a plain to-do the app
// derives from missing input. Only the first two are rendered in the accent.
export type AppNotificationType = 'risk' | 'tip' | 'reminder';

// Mock data for now — no grades/risk model exists yet.
export type AppNotification = {
	id: string;
	type: AppNotificationType;
	// True when the assistant produced this. Drives the #5B5FC7 treatment.
	aiGenerated: boolean;
	message: string;
	studentName?: string;
	courseName?: string;
	// Extra context for the metadata line, when the course name is already part
	// of the message (reminders name their course inline).
	detail?: string;
	// Overrides the per-type default icon; reminders vary by what's pending.
	icon?: IconName;
	createdAt: Date;
	read: boolean;
};

