// App-side data model. Wire shapes live in $lib/api/dto; the mappers in
// $lib/api translate between the two.

import type { IconName } from './icons';
import type { Tier } from './levels';

// --- View models built from the API ---

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
};

// One entry per student per session, built from the session roster. It carries
// no attendance: the lesson screen is a recording screen and nothing in the app
// captures asistencia any more (see the route's SPEC.md).
export type Entry = {
	// Natural key `${sessionId}:${studentId}` — the server has no entry id.
	id: string;
	sessionId: string;
	studentId: string;
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

// One entry of the competency index — the typographic control that scopes a
// whole screen to one competencia. `hasLevel` deliberately means different
// things per screen (closed for the class / this student has a level); the
// component only renders the three states, the screen decides which is which.
export type CompetencyIndexItem = {
	id: string;
	// Área competencias show a numeral, transversales a short mono code.
	label: string;
	kind: 'area' | 'transversal' | 'adicional_area' | 'adicional_libre';
	hasLevel: boolean;
};

// --- Niveles de logro por competencia (RVM 094-2020 / 048-2024) ---

// The teacher's asserted MINEDU level for one competency in one period, plus
// conclusión descriptiva state. `level` is the official record and nothing
// derives it: the teacher judges the period's evidence against the criterios
// (RVM 094-2020, 5.1.1.3 p.2-3). There is deliberately no suggested level.
export type CompetencyLevel = {
	competencyId: string;
	code: string;
	name: string;
	kind: 'area' | 'transversal' | 'adicional_area' | 'adicional_libre';
	// Null means the competency was not developed/evaluated this period —
	// a valid state (5.1.2.2 p.1). Render blank, never as C.
	level: Tier | null;
	assertedAt: Date | null;
	// Why a conclusión descriptiva is mandatory here, decided server-side.
	conclusionRequired: boolean;
	conclusionRequirement: 'level_c' | 'consecutive_c' | 'inclusion_support' | 'optional';
	conclusionBody: string | null;
	conclusionStatus: 'draft' | 'final' | null;
};
