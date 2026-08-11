// Data model — persisted to IndexedDB exactly as defined here.

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

// A session is one block of time in one class. One session per period.
export type Session = {
	id: string;
	courseId: string;
	date: Date;
	startTime: string; // "10:00"
	endTime: string; // "12:00"
	blocks: Block[];
};

export type Block = { kind: 'lesson'; topic?: string };

// Assessments are course-level, not session-level.
export type Assessment = {
	id: string;
	courseId: string;
	name: string; // "Quiz — fractions"
	type: 'quiz' | 'midterm' | 'final';
	maxScore: number;
	status: 'planned' | 'administered' | 'graded';
};

export type Attendance = 'present' | 'absent';

// 0=not rated, 1-3=star rating.
export type Participation = 0 | 1 | 2 | 3;

// One entry per student per session.
export type Entry = {
	id: string;
	sessionId: string;
	studentId: string;
	attendance: Attendance | null;
	participation: Participation | null;
	notes: Note[];
};

export type NoteTag = 'academic' | 'behavior' | 'logistics';

export type Note = {
	id: string;
	entryId: string;
	audioBlob: Blob; // the source of truth
	transcript: string | null; // stubbed for MVP
	tag?: NoteTag;
	createdAt: Date;
};

export type AppNotificationType = 'risk' | 'tip';

// Mock data for now — no grades/risk model exists yet.
export type AppNotification = {
	id: string;
	type: AppNotificationType;
	message: string;
	studentName?: string;
	createdAt: Date;
	read: boolean;
};

// Grade formula — in the real system this is authored by the academic
// supervisor and served by the backend. For now it's a static local config.
export type GradeComponentSource = 'participation' | 'assessment';

export type GradeComponent = {
	id: string;
	label: string;
	source: GradeComponentSource;
	assessmentId?: string; // required when source === 'assessment'
	weight: number; // percent; all components in a formula should sum to 100
};

export type GradeFormula = {
	courseId: string;
	components: GradeComponent[];
};

// Teacher-entered score for one grade-formula component. For 'assessment'
// components this is raw points earned (out of that assessment's maxScore);
// for the 'participation' component it's a 0-100 percent directly.
export type Score = {
	id: string;
	studentId: string;
	componentId: string;
	value: number;
};
