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

export type Block = { kind: 'lesson'; topic?: string } | { kind: 'assessment'; assessmentId: string };

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

// 0=none, 1=low, 2=good, 3=excellent. Numbers so they sort.
// (The UI spec defines a fourth "excellent" level on top of the base 0/1/2 model.)
export type Participation = 0 | 1 | 2 | 3;

// One entry per student per session.
export type Entry = {
	id: string;
	sessionId: string;
	studentId: string;
	attendance: Attendance | null;
	participation: Participation | null;
	tookAssessment?: boolean | null; // only if session has an assessment block
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

export type SessionMode = 'lesson' | 'lesson+assessment' | 'assessment';
