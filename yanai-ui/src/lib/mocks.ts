// Static display data for the four views that have no backend yet: Home,
// Class dashboard, and Profile. The Lesson and Student-grades views read real
// data from IndexedDB instead.
//
// SEEDED_COURSE_ID is the one course that is actually persisted (see seed.ts).
// Its Home card and dashboard link through to the live lesson flow; the rest
// are display-only.

import type { IconName } from './icons';

export const SEEDED_COURSE_ID = 'course-math-8b';

export const TEACHER = {
	initials: 'JQ',
	shortName: 'Janice Q',
	fullName: 'Janice Quispe',
	role: 'Docente de Secundaria',
	school: 'Cristo Rey',
	schoolFull: 'I.E. Cristo Rey · Cusco',
	since: 'Desde marzo 2021 · 5 años',
};

// --- 01 Inicio ---

export type CourseStatus = 'live' | 'pending' | 'idle';

export type HomeCourse = {
	id: string;
	name: string;
	icon: IconName;
	schedule: string[];
	status: CourseStatus;
	bucket: 'today' | 'week';
	/** Only the seeded course has a real dashboard behind it. */
	real: boolean;
};

export const HOME_COURSES: HomeCourse[] = [
	{
		id: SEEDED_COURSE_ID,
		name: 'Matemática 8B',
		icon: 'calculator',
		schedule: ['10:00 – 12:00'],
		status: 'pending',
		bucket: 'today',
		real: true,
	},
	{
		id: 'course-comunicacion-5a',
		name: 'Comunicación 5A',
		icon: 'book',
		schedule: ['13:00 – 14:30'],
		status: 'idle',
		bucket: 'today',
		real: false,
	},
	{
		id: 'course-historia-5c',
		name: 'Historia 5to C',
		icon: 'bank',
		schedule: ['Lunes 11:30 – 12:30', 'Martes 3:00 – 4:00 PM'],
		status: 'live',
		bucket: 'week',
		real: false,
	},
	{
		id: 'course-geografia-3a',
		name: 'Geografía 3ro A',
		icon: 'world',
		schedule: ['Miércoles 9:00 – 10:00'],
		status: 'idle',
		bucket: 'week',
		real: false,
	},
];

// --- 02 Clase — panel ---

export type TierSlice = { tier: 'AD' | 'A' | 'B' | 'C'; count: number };

export type RiskStudent = { name: string; reason: string };

export type Pending = { icon: IconName; title: string; detail: string };

export type SessionRef = {
	day: string;
	month: string;
	title: string;
	detail?: string;
	chips?: Array<{ text: string; tone: 'ok' | 'bad' }>;
};

export type ClassDashboard = {
	name: string;
	summary: string;
	todayLabel: string;
	todayTime: string;
	todayTopic: string;
	stats: { gradesEntered: string; attendance: string; atRisk: string };
	distribution: TierSlice[];
	risk: RiskStudent[];
	pending: Pending[];
	upcoming: SessionRef[];
	previous: SessionRef[];
};

export const CLASS_DASHBOARD: ClassDashboard = {
	name: 'Inglés 5to B',
	summary: '30 alumnos · 4 sesiones/semana',
	todayLabel: 'HOY · SIN INICIAR',
	todayTime: '10:00 – 11:00 AM',
	todayTopic: 'Lección: Present perfect tense',
	stats: { gradesEntered: '14/20', attendance: '94%', atRisk: '2' },
	distribution: [
		{ tier: 'AD', count: 4 },
		{ tier: 'A', count: 18 },
		{ tier: 'B', count: 6 },
		{ tier: 'C', count: 2 },
	],
	risk: [
		{ name: 'Sofía Ramírez', reason: '3 ausencias seguidas' },
		{ name: 'Diego Torres', reason: 'Bajó de A a B en 3 clases' },
	],
	pending: [
		{
			icon: 'checklist',
			title: 'Notas pendientes',
			detail: 'Listening: diálogos cortos · 3 alumnos',
		},
		{ icon: 'clock', title: 'Asistencia sin marcar', detail: 'Hoy · 10:00–11:00' },
	],
	upcoming: [
		{ day: '12', month: 'AGO', title: 'Grammar review', detail: '10:00 – 11:00 AM' },
		{ day: '14', month: 'AGO', title: 'Reading comprehension', detail: '10:00 – 11:00 AM' },
	],
	previous: [
		{
			day: '3',
			month: 'AGO',
			title: 'Vocabulario: rutinas diarias',
			chips: [
				{ text: '30/30 presente', tone: 'ok' },
				{ text: '✓ Comentarios', tone: 'ok' },
			],
		},
		{
			day: '1',
			month: 'AGO',
			title: 'Listening: diálogos cortos',
			chips: [
				{ text: '29/30 presente', tone: 'ok' },
				{ text: '3 pendientes', tone: 'bad' },
			],
		},
		{
			day: '28',
			month: 'JUL',
			title: 'Simple past — ejercicios',
			chips: [
				{ text: '30/30 presente', tone: 'ok' },
				{ text: '✓ Comentarios', tone: 'ok' },
			],
		},
	],
};

// --- 06 Perfil ---

export type ProfileStat = { value: string; label: string };
export type ActivityRow = { icon: IconName; label: string; value: string; danger?: boolean };
export type GradeGroup = {
	label: string;
	classes: Array<{ name: string; students: number; perWeek: number }>;
};

export const PROFILE_STATS: ProfileStat[] = [
	{ value: '20', label: 'Clases' },
	{ value: '542', label: 'Alumnos' },
	{ value: '30h', label: 'Semanales' },
];

export const PROFILE_ACTIVITY: ActivityRow[] = [
	{ icon: 'presentation', label: 'Clases dictadas', value: '214' },
	{ icon: 'clipboard-check', label: 'Asistencias registradas', value: '209 / 214' },
	{ icon: 'mic', label: 'Notas de voz', value: '486' },
	{ icon: 'checklist', label: 'Evaluaciones registradas', value: '52' },
	{ icon: 'flag', label: 'Alumnos en seguimiento', value: '23', danger: true },
];

export const PROFILE_CLASSES: GradeGroup[] = [
	{
		label: '1ER GRADO',
		classes: [
			{ name: 'Geografía 1ro A', students: 28, perWeek: 2 },
			{ name: 'Geografía 1ro B', students: 27, perWeek: 2 },
			{ name: 'Geografía 1ro C', students: 26, perWeek: 2 },
		],
	},
	{
		label: '2DO GRADO',
		classes: [
			{ name: 'Historia 2do A', students: 30, perWeek: 3 },
			{ name: 'Historia 2do B', students: 29, perWeek: 3 },
			{ name: 'Geografía 2do A', students: 30, perWeek: 2 },
			{ name: 'Geografía 2do B', students: 28, perWeek: 2 },
		],
	},
	{
		label: '3ER GRADO',
		classes: [
			{ name: 'Historia 3ro A', students: 27, perWeek: 3 },
			{ name: 'Historia 3ro B', students: 26, perWeek: 3 },
			{ name: 'Geografía 3ro A', students: 26, perWeek: 2 },
			{ name: 'Tutoría 3ro A', students: 26, perWeek: 1 },
		],
	},
	{
		label: '4TO GRADO',
		classes: [
			{ name: 'Historia 4to A', students: 31, perWeek: 3 },
			{ name: 'Historia 4to B', students: 30, perWeek: 3 },
			{ name: 'Historia 4to C', students: 28, perWeek: 3 },
			{ name: 'Geografía 4to A', students: 29, perWeek: 2 },
			{ name: 'Geografía 4to B', students: 27, perWeek: 2 },
		],
	},
	{
		label: '5TO GRADO',
		classes: [
			{ name: 'Historia 5to A', students: 29, perWeek: 3 },
			{ name: 'Historia 5to C', students: 29, perWeek: 2 },
			{ name: 'Geografía 5to A', students: 28, perWeek: 2 },
			{ name: 'Tutoría 5to A', students: 28, perWeek: 1 },
		],
	},
];

export const APP_VERSION = 'Yanai v1.0.4';

// --- 04 Alumno — notas ---

// The voice-note digest is an assistant output; there's no summarization
// backend yet, so the bullets are sample copy.
export const VOICE_NOTE_SUMMARY = {
	noteCount: 6,
	bullets: [
		'Participa más en trabajos grupales que individuales',
		'Dificultad recurrente con tiempos verbales compuestos',
		'Mejoró pronunciación desde julio',
		'2 marcas de comportamiento este bimestre',
	],
};
