// In-memory mock of the term-planning API (mawta-server/docs/api-planificacion.md).
//
// PUBLIC_PLANNING_API=mock routes every planning endpoint here instead of the
// server, so the whole flow can be built and walked before the backend
// verticals land. It keeps one class of San Felipe — 1.º de secundaria,
// Matemática — with the current term around today, and answers for any class
// id: screens pass the real course id and the mock ignores it.
//
// The mock follows the contract, not just its happy path: writes are validated
// with the domain error codes and their HTTP statuses (thrown as ApiError),
// derived fields (class dates, competency status, coverage counts, warnings)
// are computed rather than stored, and generations run in the background —
// pending for about two seconds, then completed with what they inserted.
// Everything generated is a pending proposal (proposed_by 'mawta', accepted_at
// null): Mawta proposes, the teacher decides, and only gaps are filled.

import { ApiError } from '../client';
import type {
	CalendarDto,
	CalendarNonTeachingDayDto,
	ClassPlanDto,
	CompetencyPlanStatus,
	CreateCriterionBody,
	CreateEvidenceBody,
	CreateExperienceBody,
	ExperienceCriterionDto,
	CurriculumDto,
	EvidenceKind,
	ExperienceDto,
	ExperienceProposalBody,
	ExperienceStatus,
	GenerationDto,
	GenerationKind,
	GenerationResultDto,
	PlannedEvidenceDto,
	SessionOutlineDto,
	UpdateCriterionBody,
	UpdateEvidenceBody,
	UpdateExperienceBody,
	UpdateSessionBody,
	ValueScale,
	WarningDto,
} from '../dto';

// ---------- small helpers ----------

// The wire is never fast on a phone; the mock should not be either, so loading
// states and disabled buttons get exercised.
const delay = (): Promise<void> =>
	new Promise((resolve) => setTimeout(resolve, 100 + Math.random() * 200));

// Callers must never hold the mock's internal objects: every read hands back a
// deep copy, so a screen cannot mutate the seed by editing what it rendered.
const clone = <T>(value: T): T => JSON.parse(JSON.stringify(value)) as T;

const newId = (): string => crypto.randomUUID();

const nowISO = (): string => new Date().toISOString();

// "YYYY-MM-DD" → local-midnight Date, so no UTC shift ever moves a class date.
function fromISO(date: string): Date {
	const [y, m, d] = date.split('-').map(Number);
	return new Date(y, (m ?? 1) - 1, d ?? 1);
}

function toISO(date: Date): string {
	const y = String(date.getFullYear()).padStart(4, '0');
	const m = String(date.getMonth() + 1).padStart(2, '0');
	const d = String(date.getDate()).padStart(2, '0');
	return `${y}-${m}-${d}`;
}

function addDays(date: Date, days: number): Date {
	const next = new Date(date);
	next.setDate(next.getDate() + days);
	return next;
}

function today(): Date {
	const now = new Date();
	return new Date(now.getFullYear(), now.getMonth(), now.getDate());
}

// Monday of the ISO week `date` sits in.
function mondayOf(date: Date): Date {
	const monday = new Date(date);
	monday.setHours(0, 0, 0, 0);
	const weekday = (monday.getDay() + 6) % 7;
	return addDays(monday, -weekday);
}

// The class meets Monday, Wednesday and Friday (3 sesiones/semana).
const CLASS_WEEKDAYS = [1, 3, 5];

// ---------- internal model ----------

interface Term {
	id: string;
	name: string;
	sequence: number;
	starts_on: string;
	ends_on: string;
	status: string;
}

interface NonTeachingRange {
	from: string;
	to: string;
	kind: 'feriado' | 'vacaciones' | 'gestion';
	label: string | null;
}

interface Capability {
	id: string;
	code: string;
	name: string;
}

interface Performance {
	id: string;
	order: number;
	text: string;
	en_proceso: boolean;
	suggested_capability_id: string | null;
}

interface Competency {
	id: string;
	code: string;
	name: string;
	capabilities: Capability[];
	performances: Performance[];
	/** Terms of this year in which the competencia was worked BEFORE this one. */
	worked_before: number[];
}

interface Experience {
	id: string;
	class_id: string;
	term_id: string;
	status: ExperienceStatus;
	title: string;
	idea_text: string;
	situation_text: string | null;
	starts_on: string;
	ends_on: string;
	competency_ids: string[];
	deleted: boolean;
}

interface Criterion {
	id: string;
	experience_id: string;
	competency_id: string;
	description: string;
	capability_ids: string[];
	performance_id: string | null;
	proposed_by: string;
	accepted_at: string | null;
	deleted: boolean;
}

interface Evidence {
	id: string;
	experience_id: string;
	name: string;
	kind: EvidenceKind;
	value_scale: ValueScale;
	max_score: number | null;
	criterion_ids: string[];
	session_date: string | null;
	proposed_by: string;
	accepted_at: string | null;
	deleted: boolean;
}

interface SessionEntry {
	experience_id: string;
	date: string;
	title: string;
	topics: string | null;
	planned_evidence_id: string | null;
	proposed_by: string;
	accepted_at: string | null;
	deleted: boolean;
}

interface Generation {
	id: string;
	kind: GenerationKind;
	status: 'pending' | 'running' | 'completed' | 'failed';
	experience_id: string | null;
	competency_id: string | null;
	result: GenerationResultDto | null;
	error: string | null;
}

// ---------- seed: San Felipe, 1S Matemática ----------

// Readable ids rather than UUIDs: the mock is a development tool and being able
// to tell `mat-c1-cap3` apart in the devtools is worth more than wire fidelity
// here. New rows created at runtime get real UUIDs.
const TERM_ID = 'term-trimestre-2';
const CLASS_ID = 'clase-1s-matematica';
const TOTAL_TERMS = 3;

// The term runs around today: it started four Mondays ago and ends eleven
// weeks after that, so "Tu trimestre" always has a current term with past and
// future class dates whichever day the mock is opened.
const TERM_START = toISO(mondayOf(today()));
const TERM = {
	id: TERM_ID,
	name: 'Trimestre II',
	sequence: 2,
	starts_on: toISO(addDays(fromISO(TERM_START), -28)),
	ends_on: toISO(addDays(fromISO(TERM_START), 74)),
	status: 'active',
} as const satisfies Term;

// One holiday and one vacation week, both ahead of today so the calendar and
// the session count visibly exclude them.
const VACATION_MONDAY = toISO(addDays(mondayOf(today()), 21));
const HOLIDAY = (() => {
	// The first class day at least nine days out, so it really removes a date.
	let candidate = addDays(today(), 9);
	while (!CLASS_WEEKDAYS.includes(candidate.getDay())) candidate = addDays(candidate, 1);
	return toISO(candidate);
})();

const NON_TEACHING_DAYS: NonTeachingRange[] = [
	{ from: HOLIDAY, to: HOLIDAY, kind: 'feriado', label: 'Feriado nacional' },
	{
		from: VACATION_MONDAY,
		to: toISO(addDays(fromISO(VACATION_MONDAY), 4)),
		kind: 'vacaciones',
		label: 'Vacaciones de medio año',
	},
];

function isNonTeaching(date: string): boolean {
	return NON_TEACHING_DAYS.some((range) => range.from <= date && date <= range.to);
}

// Distinct dates with a scheduled session in the range, non-teaching days
// excluded — a double block would still be one date.
function classDatesBetween(from: string, to: string): string[] {
	const dates: string[] = [];
	for (let day = fromISO(from); day <= fromISO(to); day = addDays(day, 1)) {
		if (!CLASS_WEEKDAYS.includes(day.getDay())) continue;
		const iso = toISO(day);
		if (isNonTeaching(iso)) continue;
		dates.push(iso);
	}
	return dates;
}

// The four competencias of Matemática with their real CNEB names, capabilities
// and 1S desempeños (Programa Curricular de Educación Secundaria, Matemática).
// Every 1S desempeño is "en proceso hacia" the cycle-VI standard level 6,
// which 2S reaches; the suggested capability is the inferred hint, never an
// official link.
const COMPETENCIES: Competency[] = [
	{
		id: 'mat-c1',
		code: 'MAT-C1',
		name: 'Resuelve problemas de cantidad',
		worked_before: [1],
		capabilities: [
			{
				id: 'mat-c1-cap1',
				code: 'MAT-C1-CAP1',
				name: 'Traduce cantidades a expresiones numéricas',
			},
			{
				id: 'mat-c1-cap2',
				code: 'MAT-C1-CAP2',
				name: 'Comunica su comprensión sobre los números y las operaciones',
			},
			{
				id: 'mat-c1-cap3',
				code: 'MAT-C1-CAP3',
				name: 'Usa estrategias y procedimientos de estimación y cálculo',
			},
			{
				id: 'mat-c1-cap4',
				code: 'MAT-C1-CAP4',
				name: 'Argumenta afirmaciones sobre las relaciones numéricas y las operaciones',
			},
		],
		performances: [
			{
				id: 'mat-c1-perf1',
				order: 1,
				en_proceso: true,
				suggested_capability_id: 'mat-c1-cap1',
				text: 'Establece relaciones entre datos y acciones de ganar, perder, comparar e igualar cantidades, o una combinación de acciones. Las transforma a expresiones numéricas (modelos) que incluyen operaciones con números enteros, expresiones fraccionarias o decimales, y aumentos o descuentos porcentuales.',
			},
			{
				id: 'mat-c1-perf2',
				order: 3,
				en_proceso: true,
				suggested_capability_id: 'mat-c1-cap2',
				text: 'Expresa, con diversas representaciones y lenguaje numérico, su comprensión del valor posicional de las cifras de un número hasta los millones, ordenando, comparando, componiendo y descomponiendo números naturales y enteros…',
			},
			{
				id: 'mat-c1-perf3',
				order: 6,
				en_proceso: true,
				suggested_capability_id: 'mat-c1-cap3',
				text: 'Selecciona y emplea estrategias de cálculo, estimación y procedimientos diversos para realizar operaciones con números enteros, expresiones fraccionarias, decimales y porcentuales, así como para calcular aumentos y descuentos porcentuales…',
			},
			{
				id: 'mat-c1-perf4',
				order: 9,
				en_proceso: true,
				suggested_capability_id: 'mat-c1-cap4',
				text: 'Plantea afirmaciones sobre las propiedades de los números y de las operaciones con números enteros y expresiones decimales. Las justifica o sustenta con ejemplos y propiedades de los números y de las operaciones.',
			},
		],
	},
	{
		id: 'mat-c2',
		code: 'MAT-C2',
		name: 'Resuelve problemas de regularidad, equivalencia y cambio',
		worked_before: [],
		capabilities: [
			{
				id: 'mat-c2-cap1',
				code: 'MAT-C2-CAP1',
				name: 'Traduce datos y condiciones a expresiones algebraicas',
			},
			{
				id: 'mat-c2-cap2',
				code: 'MAT-C2-CAP2',
				name: 'Comunica su comprensión sobre las relaciones algebraicas',
			},
			{
				id: 'mat-c2-cap3',
				code: 'MAT-C2-CAP3',
				name: 'Usa estrategias y procedimientos para encontrar reglas generales',
			},
			{
				id: 'mat-c2-cap4',
				code: 'MAT-C2-CAP4',
				name: 'Argumenta afirmaciones sobre relaciones de cambio y equivalencia',
			},
		],
		performances: [
			{
				id: 'mat-c2-perf1',
				order: 1,
				en_proceso: true,
				suggested_capability_id: 'mat-c2-cap1',
				text: 'Establece relaciones entre datos, regularidades, valores desconocidos, o relaciones de equivalencia o variación entre dos magnitudes. Transforma esas relaciones a expresiones algebraicas (modelo) que incluyen progresiones aritméticas, ecuaciones lineales, desigualdades, funciones lineales o proporcionalidad directa.',
			},
			{
				id: 'mat-c2-perf2',
				order: 3,
				en_proceso: true,
				suggested_capability_id: 'mat-c2-cap2',
				text: 'Expresa, con diversas representaciones gráficas, tabulares y simbólicas, y con lenguaje algebraico, su comprensión sobre la formación de un patrón gráfico o una progresión aritmética…',
			},
			{
				id: 'mat-c2-perf3',
				order: 7,
				en_proceso: true,
				suggested_capability_id: 'mat-c2-cap3',
				text: 'Selecciona y emplea recursos, estrategias heurísticas y procedimientos pertinentes a las condiciones del problema, como determinar términos desconocidos en un patrón gráfico o progresión aritmética, simplificar expresiones algebraicas y solucionar ecuaciones…',
			},
			{
				id: 'mat-c2-perf4',
				order: 8,
				en_proceso: true,
				suggested_capability_id: 'mat-c2-cap4',
				text: 'Plantea afirmaciones sobre las propiedades de igualdad que sustentan la simplificación de ambos miembros de una ecuación. Las justifica usando ejemplos y sus conocimientos matemáticos.',
			},
		],
	},
	{
		id: 'mat-c3',
		code: 'MAT-C3',
		name: 'Resuelve problemas de forma, movimiento y localización',
		worked_before: [1],
		capabilities: [
			{
				id: 'mat-c3-cap1',
				code: 'MAT-C3-CAP1',
				name: 'Modela objetos con formas geométricas y sus transformaciones',
			},
			{
				id: 'mat-c3-cap2',
				code: 'MAT-C3-CAP2',
				name: 'Comunica su comprensión sobre las formas y relaciones geométricas',
			},
			{
				id: 'mat-c3-cap3',
				code: 'MAT-C3-CAP3',
				name: 'Usa estrategias y procedimientos para orientarse en el espacio',
			},
			{
				id: 'mat-c3-cap4',
				code: 'MAT-C3-CAP4',
				name: 'Argumenta afirmaciones sobre relaciones geométricas',
			},
		],
		performances: [
			{
				id: 'mat-c3-perf1',
				order: 1,
				en_proceso: true,
				suggested_capability_id: 'mat-c3-cap1',
				text: 'Establece relaciones entre las características y los atributos medibles de objetos reales o imaginarios. Asocia estas características y las representa con formas bidimensionales compuestas y tridimensionales…',
			},
			{
				id: 'mat-c3-perf2',
				order: 3,
				en_proceso: true,
				suggested_capability_id: 'mat-c3-cap2',
				text: 'Expresa, con dibujos, construcciones con regla y compás, con material concreto y con lenguaje geométrico, su comprensión sobre las propiedades de las rectas paralelas, perpendiculares y secantes, y de los prismas, cuadriláteros, triángulos y círculos…',
			},
			{
				id: 'mat-c3-perf3',
				order: 6,
				en_proceso: true,
				suggested_capability_id: 'mat-c3-cap3',
				text: 'Selecciona y emplea estrategias heurísticas, recursos o procedimientos para determinar la longitud, el perímetro, el área o el volumen de prismas, cuadriláteros y triángulos…',
			},
			{
				id: 'mat-c3-perf4',
				order: 8,
				en_proceso: true,
				suggested_capability_id: 'mat-c3-cap4',
				text: 'Plantea afirmaciones sobre las relaciones y propiedades que descubre entre los objetos, entre objetos y formas geométricas, y entre las formas geométricas. Las justifica con ejemplos y sus conocimientos geométricos.',
			},
		],
	},
	{
		id: 'mat-c4',
		code: 'MAT-C4',
		name: 'Resuelve problemas de gestión de datos e incertidumbre',
		worked_before: [],
		capabilities: [
			{
				id: 'mat-c4-cap1',
				code: 'MAT-C4-CAP1',
				name: 'Representa datos con gráficos y medidas estadísticas o probabilísticas',
			},
			{
				id: 'mat-c4-cap2',
				code: 'MAT-C4-CAP2',
				name: 'Comunica la comprensión de los conceptos estadísticos y probabilísticos',
			},
			{
				id: 'mat-c4-cap3',
				code: 'MAT-C4-CAP3',
				name: 'Usa estrategias y procedimientos para recopilar y procesar datos',
			},
			{
				id: 'mat-c4-cap4',
				code: 'MAT-C4-CAP4',
				name: 'Sustenta conclusiones o decisiones con base en información obtenida',
			},
		],
		performances: [
			{
				id: 'mat-c4-perf1',
				order: 1,
				en_proceso: true,
				suggested_capability_id: 'mat-c4-cap1',
				text: 'Representa las características de una población en estudio asociándolas a variables cualitativas nominales y ordinales, o cuantitativas discretas, y expresa el comportamiento de los datos a través de gráficos de barras, gráficos circulares y medidas de tendencia central.',
			},
			{
				id: 'mat-c4-perf2',
				order: 3,
				en_proceso: true,
				suggested_capability_id: 'mat-c4-cap2',
				text: 'Expresa con diversas representaciones y lenguaje matemático su comprensión sobre la media, la mediana y la moda para datos no agrupados, según el contexto de la población en estudio…',
			},
			{
				id: 'mat-c4-perf3',
				order: 5,
				en_proceso: true,
				suggested_capability_id: 'mat-c4-cap3',
				text: 'Recopila datos de variables cualitativas o cuantitativas discretas mediante encuestas, seleccionando y empleando procedimientos y recursos. Los procesa y organiza en tablas con el propósito de analizarlos y producir información.',
			},
			{
				id: 'mat-c4-perf4',
				order: 7,
				en_proceso: true,
				suggested_capability_id: 'mat-c4-cap4',
				text: 'Plantea afirmaciones o conclusiones sobre la información cualitativa y cuantitativa de una población, o la probabilidad de ocurrencia de sucesos. Las justifica usando la información obtenida y sus conocimientos estadísticos.',
			},
		],
	},
];

const competencyById = (id: string): Competency | undefined =>
	COMPETENCIES.find((competency) => competency.id === id);

const capabilityById = (
	id: string
): { competency: Competency; capability: Capability } | undefined => {
	for (const competency of COMPETENCIES) {
		const capability = competency.capabilities.find((item) => item.id === id);
		if (capability) return { competency, capability };
	}
	return undefined;
};

// ---------- mutable state ----------

let experiences: Experience[] = [];
let criteria: Criterion[] = [];
let evidences: Evidence[] = [];
let sessions: SessionEntry[] = [];
const generations = new Map<string, Generation>();

// ---------- the seeded experience ----------

// One planned experience so "Tu trimestre" is never empty: the tiendita of the
// prototype, already confirmed, with accepted criteria and evidences, one
// pending criterio from Mawta, sessions on the first dates and three class
// dates left empty (so "Generar con Mawta" has a gap to fill).
function seedExperience(): void {
	const startsOn = TERM.starts_on;
	const endsOn = toISO(addDays(fromISO(startsOn), 20));
	const dates = classDatesBetween(startsOn, endsOn);

	const experience: Experience = {
		id: 'exp-tiendita',
		class_id: CLASS_ID,
		term_id: TERM.id,
		status: 'planificada',
		title: 'La tiendita escolar',
		idea_text:
			'Quiero armar una tiendita en el aula: ponemos precios, compramos, damos el vuelto y registramos qué se vende más.',
		situation_text:
			'Organizamos la tiendita de la feria del aula: ponemos precios con descuentos, cobramos, damos el vuelto y registramos qué se vende más para decidir qué ofrecer en la próxima feria.',
		starts_on: startsOn,
		ends_on: endsOn,
		competency_ids: ['mat-c1', 'mat-c4'],
		deleted: false,
	};
	experiences = [experience];

	const acceptedAt = toISO(addDays(today(), -20)) + 'T14:02:00Z';
	criteria = [
		{
			id: 'crit-tiendita-1',
			experience_id: experience.id,
			competency_id: 'mat-c1',
			description:
				'Plantea la expresión numérica que modela una compra con descuento porcentual y comprueba que refleja los datos del problema.',
			capability_ids: ['mat-c1-cap1'],
			performance_id: 'mat-c1-perf1',
			proposed_by: 'teacher',
			accepted_at: acceptedAt,
			deleted: false,
		},
		{
			id: 'crit-tiendita-2',
			experience_id: experience.id,
			competency_id: 'mat-c1',
			description:
				'Calcula el vuelto con estrategias de estimación y cálculo mental, redondeando a la unidad más cercana.',
			capability_ids: ['mat-c1-cap3'],
			performance_id: 'mat-c1-perf3',
			proposed_by: 'teacher',
			accepted_at: acceptedAt,
			deleted: false,
		},
		{
			id: 'crit-tiendita-3',
			experience_id: experience.id,
			competency_id: 'mat-c1',
			description:
				'Justifica con ejemplos y propiedades de las operaciones el procedimiento que eligió para dar el vuelto.',
			capability_ids: ['mat-c1-cap4'],
			performance_id: 'mat-c1-perf4',
			proposed_by: 'teacher',
			accepted_at: acceptedAt,
			deleted: false,
		},
		{
			// The one pending proposal: Mawta suggested it and the teacher has
			// not accepted or edited it yet.
			id: 'crit-tiendita-4',
			experience_id: experience.id,
			competency_id: 'mat-c1',
			description:
				'Expresa con representaciones el valor posicional de los precios hasta los millones al ordenar la lista de la tiendita.',
			capability_ids: ['mat-c1-cap2'],
			performance_id: 'mat-c1-perf2',
			proposed_by: 'mawta',
			accepted_at: null,
			deleted: false,
		},
		{
			id: 'crit-tiendita-5',
			experience_id: experience.id,
			competency_id: 'mat-c4',
			description:
				'Registra en una tabla de frecuencias los productos que se venden cada día de la feria.',
			capability_ids: ['mat-c4-cap3'],
			performance_id: 'mat-c4-perf3',
			proposed_by: 'teacher',
			accepted_at: acceptedAt,
			deleted: false,
		},
		{
			id: 'crit-tiendita-6',
			experience_id: experience.id,
			competency_id: 'mat-c4',
			description:
				'Representa las ventas en un gráfico de barras e interpreta la media y la moda del conjunto de datos.',
			capability_ids: ['mat-c4-cap1'],
			performance_id: 'mat-c4-perf1',
			proposed_by: 'teacher',
			accepted_at: acceptedAt,
			deleted: false,
		},
	];

	evidences = [
		{
			id: 'ev-tiendita-precios',
			experience_id: experience.id,
			name: 'Lista de precios de la tiendita',
			kind: 'produccion',
			value_scale: 'numeric',
			max_score: 20,
			criterion_ids: ['crit-tiendita-1', 'crit-tiendita-4'],
			session_date: dates[0] ?? null,
			proposed_by: 'teacher',
			accepted_at: acceptedAt,
			deleted: false,
		},
		{
			id: 'ev-tiendita-prueba',
			experience_id: experience.id,
			name: 'Prueba escrita: vueltos y descuentos',
			kind: 'produccion',
			value_scale: 'numeric',
			max_score: 20,
			criterion_ids: ['crit-tiendita-2', 'crit-tiendita-3'],
			session_date: null,
			proposed_by: 'teacher',
			accepted_at: acceptedAt,
			deleted: false,
		},
	];

	const titles: { title: string; topics: string }[] = [
		{ title: '¿Qué vendemos y a cuánto?', topics: 'precios, valor posicional' },
		{ title: 'Monedas y billetes', topics: 'expresiones decimales, equivalencias' },
		{ title: 'Compras con descuento', topics: 'porcentajes, estrategias de cálculo' },
		{ title: '¿Cuánto me dan de vuelto?', topics: 'estimación, operación inversa' },
		{ title: 'Registramos las ventas', topics: 'tablas de frecuencia' },
		{ title: '¿Qué se vendió más?', topics: 'gráficos de barras, media y moda' },
	];
	sessions = titles.map((entry, index) => ({
		experience_id: experience.id,
		date: dates[index] ?? '',
		title: entry.title,
		topics: entry.topics,
		// Placement is one relation seen from both sides: the first session
		// holds the lista de precios.
		planned_evidence_id: index === 0 ? 'ev-tiendita-precios' : null,
		proposed_by: 'teacher',
		accepted_at: acceptedAt,
		deleted: false,
	}));
}

seedExperience();

// ---------- lookups ----------

const liveExperiences = (): Experience[] => experiences.filter((item) => !item.deleted);

const experienceById = (id: string): Experience | undefined =>
	experiences.find((item) => item.id === id && !item.deleted);

const liveCriteriaOf = (experienceId: string): Criterion[] =>
	criteria.filter((item) => item.experience_id === experienceId && !item.deleted);

const criterionById = (id: string): Criterion | undefined =>
	criteria.find((item) => item.id === id && !item.deleted);

const liveEvidencesOf = (experienceId: string): Evidence[] =>
	evidences.filter((item) => item.experience_id === experienceId && !item.deleted);

const evidenceById = (id: string): Evidence | undefined =>
	evidences.find((item) => item.id === id && !item.deleted);

const liveSessionsOf = (experienceId: string): SessionEntry[] =>
	sessions.filter((item) => item.experience_id === experienceId && !item.deleted);

const sessionOf = (experienceId: string, date: string): SessionEntry | undefined =>
	sessions.find(
		(item) => item.experience_id === experienceId && item.date === date && !item.deleted
	);

// ---------- derived fields (computed, never stored) ----------

function pendingCount(experienceId: string): number {
	const pending = (proposer: string, accepted: string | null): boolean =>
		proposer === 'mawta' && accepted === null;
	return (
		liveCriteriaOf(experienceId).filter((item) => pending(item.proposed_by, item.accepted_at))
			.length +
		liveEvidencesOf(experienceId).filter((item) => pending(item.proposed_by, item.accepted_at))
			.length +
		liveSessionsOf(experienceId).filter((item) => pending(item.proposed_by, item.accepted_at))
			.length
	);
}

// Capabilities of the competencia with at least one criterio in the experience.
// Coverage and warnings count accepted criteria only, as the server does: a
// pending proposal is not yet the teacher's. Generation fills gaps counting
// pending ones too (acceptedOnly false), so it never proposes twice.
function coveredCapabilities(
	experienceId: string,
	competencyId: string,
	acceptedOnly = true
): Set<string> {
	const covered = new Set<string>();
	for (const criterion of liveCriteriaOf(experienceId)) {
		if (criterion.competency_id !== competencyId) continue;
		if (acceptedOnly && criterion.accepted_at === null) continue;
		for (const capabilityId of criterion.capability_ids) covered.add(capabilityId);
	}
	return covered;
}

// Competencia status per the contract: 'planificada' with a non-deleted
// experience this term; otherwise 'toca' when it still needs terms to be worked
// twice in the year and the terms left (this one included) are no more than it
// needs; 'puede_esperar' otherwise.
function competencyStatus(competency: Competency): CompetencyPlanStatus {
	const planned = liveExperiences().some(
		(experience) =>
			experience.term_id === TERM.id && experience.competency_ids.includes(competency.id)
	);
	if (planned) return 'planificada';
	const worked = workedTerms(competency).length;
	const needed = Math.max(0, 2 - worked);
	const remaining = TOTAL_TERMS - TERM.sequence + 1;
	return needed > 0 && remaining <= needed ? 'toca' : 'puede_esperar';
}

function workedTerms(competency: Competency): number[] {
	const worked = [...competency.worked_before];
	const planned = liveExperiences().some(
		(experience) =>
			experience.term_id === TERM.id && experience.competency_ids.includes(competency.id)
	);
	if (planned && !worked.includes(TERM.sequence)) worked.push(TERM.sequence);
	return worked.sort((a, b) => a - b);
}

// Warnings never block; they are what the summary screen shows.
function experienceWarnings(experience: Experience): WarningDto[] {
	const warnings: WarningDto[] = [];
	for (const competencyId of experience.competency_ids) {
		const competency = competencyById(competencyId);
		if (!competency) continue;
		const covered = coveredCapabilities(experience.id, competencyId);
		for (const capability of competency.capabilities) {
			if (covered.has(capability.id)) continue;
			warnings.push({
				code: 'capability_without_criterion',
				competency_id: competencyId,
				capability_id: capability.id,
			});
		}
	}
	const pending = pendingCount(experience.id);
	if (pending > 0) warnings.push({ code: 'pending_proposals', count: pending });
	return warnings;
}

// ---------- validation (the contract's domain errors) ----------

// A domain error, thrown exactly as the server would answer it: the code and
// the HTTP status are the contract's, so the UI can show its own text.
function fail(status: number, code: string, message: string): never {
	throw new ApiError(status, code, message);
}

// A competency is valid for this class when it is one of the area's four.
function requireCompetencies(ids: string[]): void {
	if (ids.length === 0) {
		fail(400, 'missing_competencies', 'Elige al menos una competencia del área.');
	}
	for (const id of ids) {
		if (!competencyById(id)) {
			fail(422, 'competency_not_in_subject', 'La competencia no pertenece al área de la clase.');
		}
	}
}

// Dates must sit inside the term (and make sense as a range at all).
function requireInsideTerm(startsOn: string, endsOn: string): void {
	if (startsOn > endsOn) {
		fail(422, 'outside_term', 'La fecha de inicio no puede ser posterior a la de fin.');
	}
	if (startsOn < TERM.starts_on || endsOn > TERM.ends_on) {
		fail(422, 'outside_term', 'La experiencia debe empezar y terminar dentro del periodo.');
	}
}

// Drafts are included in the overlap exclusion: two drafts cannot take the same
// weeks either.
function requireNoOverlap(startsOn: string, endsOn: string, exceptId?: string): void {
	const clash = liveExperiences().find(
		(experience) =>
			experience.id !== exceptId &&
			experience.term_id === TERM.id &&
			startsOn <= experience.ends_on &&
			endsOn >= experience.starts_on
	);
	if (clash) {
		fail(409, 'experience_overlap', `Las fechas se cruzan con otra experiencia: ${clash.title}.`);
	}
}

// A session or placed-evidence date must be a class date inside the experience
// and not a non-teaching day.
function requireClassDateIn(experience: Experience, date: string): void {
	const inside = date >= experience.starts_on && date <= experience.ends_on;
	if (!inside || !CLASS_WEEKDAYS.includes(fromISO(date).getDay()) || isNonTeaching(date)) {
		fail(422, 'date_not_in_experience', 'La fecha no es un día de clase dentro de la experiencia.');
	}
}

function requireCriterionBody(experience: Experience, body: CreateCriterionBody): void {
	if (!experience.competency_ids.includes(body.competency_id)) {
		fail(422, 'competency_not_in_subject', 'La competencia no es parte de la experiencia.');
	}
	const competency = competencyById(body.competency_id);
	if (!competency) {
		fail(422, 'competency_not_in_subject', 'La competencia no pertenece al área de la clase.');
	}
	if (body.capability_ids.length === 0) {
		fail(422, 'criterion_needs_capability', 'El criterio debe mirar al menos una capacidad.');
	}
	for (const capabilityId of body.capability_ids) {
		const found = capabilityById(capabilityId);
		if (!found || found.competency.id !== body.competency_id) {
			fail(
				422,
				'capability_not_in_competency',
				'Una de las capacidades no pertenece a esa competencia.'
			);
		}
	}
	if (
		body.performance_id !== undefined &&
		!competency.performances.some((performance) => performance.id === body.performance_id)
	) {
		fail(
			422,
			'performance_not_in_grade',
			'El desempeño no es de esa competencia para el grado de la clase.'
		);
	}
}

function requireEvidenceCriteria(experience: Experience, criterionIds: string[]): void {
	if (criterionIds.length === 0) {
		fail(400, 'missing_criteria', 'La evidencia debe observar al menos un criterio.');
	}
	const own = new Set(liveCriteriaOf(experience.id).map((criterion) => criterion.id));
	for (const criterionId of criterionIds) {
		if (!own.has(criterionId)) {
			fail(422, 'criterion_other_experience', 'Un criterio no pertenece a esta experiencia.');
		}
	}
}

const EVIDENCE_KINDS: EvidenceKind[] = ['produccion', 'actuacion'];

function requireEvidenceKind(kind: string): void {
	if (!EVIDENCE_KINDS.includes(kind as EvidenceKind)) {
		fail(400, 'bad_request', 'El tipo de evidencia no es válido.');
	}
}

// ---------- placement (one relation seen from both sides) ----------

// Setting an evidence's session_date and setting a session's
// planned_evidence_id are the same change; both sides stay in step, and at
// most one evidencia sits on a class date.
function placeEvidence(experience: Experience, evidence: Evidence, date: string | null): void {
	for (const entry of sessions) {
		if (entry.planned_evidence_id === evidence.id && entry.date !== date) {
			entry.planned_evidence_id = null;
		}
	}
	if (date !== null) {
		const entry = sessionOf(experience.id, date);
		if (entry) {
			// At most one evidencia per class date: the previous one, if any,
			// simply stops being placed.
			for (const other of evidences) {
				if (other.id !== evidence.id && other.session_date === date) other.session_date = null;
			}
			entry.planned_evidence_id = evidence.id;
		}
	}
	evidence.session_date = date;
}

// ---------- generations ----------

// A generation starts pending and completes after about two seconds, exactly
// as the queued job would: the route returns at once and the app polls.
const GENERATION_MS = 2000;

function startGeneration(
	kind: GenerationKind,
	experienceId: string | null,
	competencyId: string | null,
	complete: (generation: Generation) => GenerationResultDto | null
): Generation {
	// A second generation of the same kind for the same experience while one is
	// pending returns the pending one.
	const running = [...generations.values()].find(
		(item) =>
			item.status === 'pending' &&
			item.kind === kind &&
			item.experience_id === experienceId &&
			(item.competency_id ?? null) === (competencyId ?? null)
	);
	if (running) return running;

	const generation: Generation = {
		id: newId(),
		kind,
		status: 'pending',
		experience_id: experienceId,
		competency_id: competencyId,
		result: null,
		error: null,
	};
	generations.set(generation.id, generation);
	setTimeout(
		() => {
			if (generation.status !== 'pending') return;
			try {
				generation.result = complete(generation);
				generation.status = 'completed';
			} catch (error) {
				generation.status = 'failed';
				generation.error =
					error instanceof Error ? error.message : 'No se pudo generar la propuesta.';
			}
		},
		GENERATION_MS + Math.random() * 500
	);
	return generation;
}

function toGenerationDto(generation: Generation): GenerationDto {
	const dto: GenerationDto = {
		id: generation.id,
		kind: generation.kind,
		status: generation.status,
	};
	if (generation.result !== null) dto.result = clone(generation.result);
	if (generation.error !== null) dto.error = generation.error;
	return dto;
}

// ---------- the agent's banks (only gaps, only from the loaded curriculum) ----------

// One criterio per capability, written from the cycle standard. The agent
// never cites a desempeño.
const CRITERIA_BANK: Record<string, { text: string }> = {
	'mat-c1-cap1': {
		text: 'Plantea la expresión numérica que modela la situación y comprueba que refleja sus datos y condiciones.',
	},
	'mat-c1-cap2': {
		text: 'Expresa con representaciones y lenguaje numérico el valor posicional y el significado de los datos de la situación.',
	},
	'mat-c1-cap3': {
		text: 'Emplea estrategias de cálculo y estimación con enteros, fracciones, decimales o porcentajes según la situación.',
	},
	'mat-c1-cap4': {
		text: 'Justifica con ejemplos y propiedades de las operaciones el procedimiento y los resultados obtenidos.',
	},
	'mat-c2-cap1': {
		text: 'Traduce la regularidad o la relación de equivalencia a una expresión algebraica o gráfica que la modele.',
	},
	'mat-c2-cap2': {
		text: 'Expresa con representaciones tabulares, gráficas y simbólicas la regla de formación del patrón.',
	},
	'mat-c2-cap3': {
		text: 'Emplea estrategias y procedimientos para hallar términos desconocidos o resolver la ecuación planteada.',
	},
	'mat-c2-cap4': {
		text: 'Plantea y justifica afirmaciones sobre las relaciones de cambio y equivalencia que descubre.',
	},
	'mat-c3-cap1': {
		text: 'Modela el objeto o la situación con formas geométricas y sus transformaciones, guardando sus propiedades.',
	},
	'mat-c3-cap2': {
		text: 'Expresa con lenguaje geométrico y construcciones su comprensión de las formas y sus propiedades.',
	},
	'mat-c3-cap3': {
		text: 'Emplea estrategias y unidades pertinentes para medir, ubicar o describir el espacio.',
	},
	'mat-c3-cap4': {
		text: 'Justifica con ejemplos y conocimientos geométricos las relaciones que descubre entre las formas.',
	},
	'mat-c4-cap1': {
		text: 'Representa los datos de la situación con gráficos y medidas de tendencia central pertinentes.',
	},
	'mat-c4-cap2': {
		text: 'Expresa con lenguaje matemático su comprensión de la media, la mediana y la moda en el contexto.',
	},
	'mat-c4-cap3': {
		text: 'Recopila y organiza en tablas los datos que la situación necesita, con procedimientos adecuados.',
	},
	'mat-c4-cap4': {
		text: 'Sustenta con la información obtenida las conclusiones o decisiones que propone.',
	},
};

// One evidencia per competencia, over the criteria nothing observes yet.
const EVIDENCE_BANK: Record<string, { name: string; kind: EvidenceKind }> = {
	'mat-c1': { name: 'Hoja de cálculo de la experiencia', kind: 'produccion' },
	'mat-c2': { name: 'Ficha de patrones de la experiencia', kind: 'produccion' },
	'mat-c3': { name: 'Maqueta y plano de la experiencia', kind: 'produccion' },
	'mat-c4': { name: 'Tabla y gráfico de la experiencia', kind: 'produccion' },
};

const SESSION_TITLES = [
	'Presentamos la situación',
	'Exploramos el problema',
	'Practicamos con nuevos datos',
	'Comparamos procedimientos',
	'Ensayamos y corregimos',
	'Sistematizamos lo aprendido',
];

// "Tengo una idea": the proposal is derived from the idea text, never saved.
const PROPOSAL_TITLES: { match: RegExp; title: string }[] = [
	{ match: /tiendita|kiosco|feria|venta/i, title: 'La tiendita escolar' },
	{ match: /paseo|viaje|excursi/i, title: 'El paseo del aula' },
	{ match: /encuesta|dato|gr[áa]fico|estad[íi]/i, title: 'La encuesta del aula' },
	{ match: /patr[óo]n|guarda|tejido|secuencia/i, title: 'Las guardas del aula' },
	{ match: /maqueta|plano|barrio|casa|dibujo/i, title: 'La maqueta de nuestro barrio' },
];

const PROPOSAL_SITUATIONS: Record<string, string> = {
	'mat-c1':
		'Organizamos la tiendita del aula: ponemos precios, calculamos descuentos y damos el vuelto, y registramos qué se vende más para decidir qué ofrecer la próxima semana.',
	'mat-c2':
		'Descubrimos los patrones que se repiten en los tejidos de la feria de la comunidad y creamos los nuestros siguiendo una regla de formación.',
	'mat-c3':
		'Armamos la maqueta del barrio con cajas y ubicamos la escuela, el mercado y la plaza, midiendo y dibujando a escala.',
	'mat-c4':
		'Hacemos una encuesta en el aula sobre un tema de interés, organizamos los datos en tablas y gráficos y decidimos con la información obtenida.',
};

// Competencias the agent detects in the idea text when the teacher did not pick.
const IDEA_KEYWORDS: { match: RegExp; competency_id: string }[] = [
	{
		match: /precio|compra|vuelto|dinero|presupuesto|cantidad|porcentaje/i,
		competency_id: 'mat-c1',
	},
	{ match: /patr[óo]n|regularidad|secuencia|regla|equivalencia/i, competency_id: 'mat-c2' },
	{ match: /figura|plano|maqueta|forma|ubicar|medir|dibujo/i, competency_id: 'mat-c3' },
	{ match: /encuesta|dato|gr[áa]fico|tabla|estad[íi]st|probabilidad/i, competency_id: 'mat-c4' },
];

// The first free three weeks inside the term, starting after today.
function proposalDates(): { starts_on: string; ends_on: string } {
	let startsOn = toISO(today());
	if (startsOn < TERM.starts_on) startsOn = TERM.starts_on;
	for (const experience of liveExperiences()) {
		if (experience.ends_on >= startsOn) startsOn = toISO(addDays(fromISO(experience.ends_on), 1));
	}
	let endsOn = toISO(addDays(fromISO(startsOn), 18));
	if (endsOn > TERM.ends_on) endsOn = TERM.ends_on;
	return { starts_on: startsOn, ends_on: endsOn };
}

// ---------- reads ----------

export async function getClassPlan(_classId: string, termId?: string): Promise<ClassPlanDto> {
	await delay();
	if (termId !== undefined && termId !== TERM.id) {
		fail(404, 'not_found', 'El periodo no existe.');
	}
	const planExperiences = liveExperiences()
		.filter((experience) => experience.term_id === TERM.id)
		.map((experience) => ({
			id: experience.id,
			title: experience.title,
			status: experience.status,
			starts_on: experience.starts_on,
			ends_on: experience.ends_on,
			class_dates: classDatesBetween(experience.starts_on, experience.ends_on).length,
			competencies: experience.competency_ids.map((competencyId) => {
				const competency = competencyById(competencyId);
				const covered = coveredCapabilities(experience.id, competencyId);
				return {
					id: competencyId,
					code: competency?.code ?? '',
					name: competency?.name ?? '',
					capabilities_total: competency?.capabilities.length ?? 0,
					capabilities_with_criteria: competency
						? competency.capabilities.filter((capability) => covered.has(capability.id)).length
						: 0,
				};
			}),
			pending_proposals: pendingCount(experience.id),
		}));

	const planCompetencies = COMPETENCIES.map((competency) => {
		const covered = new Set<string>();
		for (const experience of liveExperiences()) {
			if (experience.term_id !== TERM.id) continue;
			if (!experience.competency_ids.includes(competency.id)) continue;
			for (const capabilityId of coveredCapabilities(experience.id, competency.id)) {
				covered.add(capabilityId);
			}
		}
		return {
			id: competency.id,
			code: competency.code,
			name: competency.name,
			status: competencyStatus(competency),
			terms_worked: workedTerms(competency),
			capabilities_total: competency.capabilities.length,
			capabilities_covered_this_term: competency.capabilities.filter((capability) =>
				covered.has(capability.id)
			).length,
		};
	});

	return clone({
		term: {
			id: TERM.id,
			name: TERM.name,
			starts_on: TERM.starts_on,
			ends_on: TERM.ends_on,
			status: TERM.status,
		},
		non_teaching_days: NON_TEACHING_DAYS,
		class_dates_total: classDatesBetween(TERM.starts_on, TERM.ends_on).length,
		experiences: planExperiences,
		competencies: planCompetencies,
	});
}

// The cycle-VI standard of each competencia, verbatim from the Programa
// Curricular de Educación Secundaria (Matemática), level 6.
const STANDARDS: Record<string, { level: number; text: string }> = {
	'mat-c1': {
		level: 6,
		text: 'Resuelve problemas referidos a las relaciones entre cantidades o magnitudes, traduciéndolas a expresiones numéricas y operativas con números naturales, enteros y racionales, aumentos y descuentos porcentuales sucesivos, verificando si estas expresiones cumplen con las condiciones iniciales del problema. Expresa su comprensión de la relación entre los órdenes del sistema de numeración decimal con las potencias de base diez, y entre las operaciones con números enteros y racionales; y las usa para interpretar enunciados o textos diversos de contenido matemático. Representa relaciones de equivalencia entre expresiones decimales, fraccionarias y porcentuales, entre unidades de masa, tiempo y monetarias; empleando lenguaje matemático. Selecciona, emplea y combina recursos, estrategias, procedimientos, y propiedades de las operaciones y de los números para estimar o calcular con enteros y racionales; y realizar conversiones entre unidades de masa, tiempo y temperatura; verificando su eficacia. Plantea afirmaciones sobre los números enteros y racionales, sus propiedades y relaciones, y las justifica mediante ejemplos y sus conocimientos de las operaciones, e identifica errores o vacíos en las argumentaciones propias o de otros y las corrige.',
	},
	'mat-c2': {
		level: 6,
		text: 'Resuelve problemas referidos a interpretar cambios constantes o regularidades entre magnitudes, valores o entre expresiones; traduciéndolas a patrones numéricos y gráficos, progresiones aritméticas, ecuaciones e inecuaciones con una incógnita, funciones lineales y afín, y relaciones de proporcionalidad directa e inversa. Comprueba si la expresión algebraica usada expresó o reprodujo las condiciones del problema. Expresa su comprensión de: la relación entre función lineal y proporcionalidad directa; las diferencias entre una ecuación e inecuación lineal y sus propiedades; la variable como un valor que cambia; el conjunto de valores que puede tomar un término desconocido para verificar una inecuación; y las usa para interpretar enunciados, expresiones algebraicas o textos diversos de contenido matemático. Selecciona, emplea y combina recursos, estrategias, métodos gráficos y procedimientos matemáticos para determinar el valor de términos desconocidos en una progresión aritmética, simplificar expresiones algebraicas y dar solución a ecuaciones e inecuaciones lineales, y evaluar funciones lineales. Plantea afirmaciones sobre propiedades de las progresiones aritméticas, ecuaciones e inecuaciones así como de una función lineal, lineal afín con base a sus experiencias, y las justifica mediante ejemplos y propiedades matemáticas; encuentra errores o vacíos en las argumentaciones propias y las de otros y las corrige.',
	},
	'mat-c3': {
		level: 6,
		text: 'Resuelve problemas en los que modela características de objetos mediante prismas, pirámides y polígonos, sus elementos y propiedades, y la semejanza y congruencia de formas geométricas; así como la ubicación y movimiento mediante coordenadas en el plano cartesiano, mapas y planos a escala, y transformaciones. Expresa su comprensión de las formas congruentes y semejantes, la relación entre una forma geométrica y sus diferentes perspectivas; usando dibujos y construcciones. Clasifica prismas, pirámides y polígonos, según sus propiedades. Selecciona y emplea estrategias, procedimientos y recursos para determinar la longitud, área o volumen de formas geométricas en unidades convencionales y para construir formas geométricas a escala. Plantea afirmaciones sobre la semejanza y congruencia de formas, relaciones entre áreas de formas geométricas; las justifica mediante ejemplos y propiedades geométricas.',
	},
	'mat-c4': {
		level: 6,
		text: 'Resuelve problemas en los que plantea temas de estudio, identificando la población pertinente y las variables cuantitativas continuas, así como cualitativas nominales y ordinales. Recolecta datos mediante encuestas y los registra en tablas de datos agrupados, así también determina la media aritmética y mediana de datos discretos; representa su comportamiento en histogramas, polígonos de frecuencia, gráficos circulares, tablas de frecuencia y medidas de tendencia central; usa el significado de las medidas de tendencia central para interpretar y comparar la información contenida en estos. Basado en ello, plantea y contrasta conclusiones, sobre las características de una población. Expresa la probabilidad de un evento aleatorio como decimal o fracción, así como su espacio muestral; e interpreta que un suceso seguro, probable e imposible, se asocia a los valores entre 0 y 1. Hace predicciones sobre la ocurrencia de eventos y las justifica.',
	},
};

// The mock answers for any class id: screens pass the real course id and the
// seed ignores it, so the flow can be walked from any class panel.
export async function getClassCurriculum(classId: string): Promise<CurriculumDto> {
	void classId;
	await delay();
	return clone({
		grade: { code: '1S', cycle: 'ciclo_vi', expected_level: 6 },
		competencies: COMPETENCIES.map((competency) => ({
			id: competency.id,
			code: competency.code,
			name: competency.name,
			kind: 'area',
			standard: STANDARDS[competency.id] ?? null,
			capabilities: competency.capabilities,
			performances: competency.performances,
		})),
	});
}

export async function getCalendar(
	_classId: string,
	from: string,
	to: string
): Promise<CalendarDto> {
	await delay();
	const nonTeaching: CalendarNonTeachingDayDto[] = [];
	for (const range of NON_TEACHING_DAYS) {
		const start = range.from < from ? from : range.from;
		const end = range.to > to ? to : range.to;
		for (let day = fromISO(start); day <= fromISO(end); day = addDays(day, 1)) {
			nonTeaching.push({ date: toISO(day), kind: range.kind, label: range.label });
		}
	}
	return clone({
		class_dates: classDatesBetween(from, to),
		non_teaching_days: nonTeaching,
	});
}

function toExperienceDto(experience: Experience): ExperienceDto {
	const competencyRefs = experience.competency_ids.map((competencyId) => {
		const competency = competencyById(competencyId);
		return {
			id: competencyId,
			code: competency?.code ?? '',
			name: competency?.name ?? '',
		};
	});
	return clone({
		id: experience.id,
		class_id: experience.class_id,
		term_id: experience.term_id,
		status: experience.status,
		title: experience.title,
		idea_text: experience.idea_text,
		situation_text: experience.situation_text,
		starts_on: experience.starts_on,
		ends_on: experience.ends_on,
		competencies: competencyRefs,
		criteria: liveCriteriaOf(experience.id).map((criterion) => ({
			id: criterion.id,
			experience_id: criterion.experience_id,
			competency_id: criterion.competency_id,
			description: criterion.description,
			capability_ids: criterion.capability_ids,
			performance_id: criterion.performance_id,
			proposed_by: criterion.proposed_by,
			accepted_at: criterion.accepted_at,
		})),
		evidences: liveEvidencesOf(experience.id).map((evidence) => ({
			id: evidence.id,
			experience_id: evidence.experience_id,
			name: evidence.name,
			kind: evidence.kind,
			value_scale: evidence.value_scale,
			max_score: evidence.max_score,
			criterion_ids: evidence.criterion_ids,
			session_date: evidence.session_date,
			proposed_by: evidence.proposed_by,
			accepted_at: evidence.accepted_at,
		})),
		sessions: liveSessionsOf(experience.id).map((entry) => ({
			date: entry.date,
			title: entry.title,
			topics: entry.topics,
			planned_evidence_id: entry.planned_evidence_id,
			proposed_by: entry.proposed_by,
			accepted_at: entry.accepted_at,
		})),
		class_dates: classDatesBetween(experience.starts_on, experience.ends_on),
		warnings: experienceWarnings(experience),
	});
}

export async function getExperience(experienceId: string): Promise<ExperienceDto> {
	await delay();
	const experience = experienceById(experienceId);
	if (!experience) fail(404, 'not_found', 'La experiencia no existe.');
	return toExperienceDto(experience);
}

// ---------- writes ----------

export async function createExperience(
	classId: string,
	body: CreateExperienceBody
): Promise<ExperienceDto> {
	await delay();
	requireCompetencies(body.competency_ids);
	requireInsideTerm(body.starts_on, body.ends_on);
	requireNoOverlap(body.starts_on, body.ends_on);
	const experience: Experience = {
		id: newId(),
		class_id: classId,
		term_id: TERM.id,
		status: 'borrador',
		title: body.title,
		idea_text: body.idea_text,
		situation_text: body.situation_text?.trim() ? body.situation_text.trim() : null,
		starts_on: body.starts_on,
		ends_on: body.ends_on,
		competency_ids: [...body.competency_ids],
		deleted: false,
	};
	experiences.push(experience);
	return toExperienceDto(experience);
}

export async function updateExperience(
	experienceId: string,
	body: UpdateExperienceBody
): Promise<ExperienceDto> {
	await delay();
	const experience = experienceById(experienceId);
	if (!experience) fail(404, 'not_found', 'La experiencia no existe.');

	const startsOn = body.starts_on ?? experience.starts_on;
	const endsOn = body.ends_on ?? experience.ends_on;
	requireInsideTerm(startsOn, endsOn);
	requireNoOverlap(startsOn, endsOn, experienceId);

	// Changing dates keeps sessions inside the new range: a session or a placed
	// evidence that would fall outside rejects the change.
	for (const entry of liveSessionsOf(experienceId)) {
		if (entry.date < startsOn || entry.date > endsOn) {
			fail(422, 'date_not_in_experience', 'Una sesión quedaría fuera de las nuevas fechas.');
		}
	}
	for (const evidence of liveEvidencesOf(experienceId)) {
		if (
			evidence.session_date !== null &&
			(evidence.session_date < startsOn || evidence.session_date > endsOn)
		) {
			fail(
				422,
				'date_not_in_experience',
				'Una evidencia colocada quedaría fuera de las nuevas fechas.'
			);
		}
	}

	if (body.competency_ids !== undefined) {
		requireCompetencies(body.competency_ids);
		// Removing a competencia that still has criteria is rejected: the
		// teacher deletes those criteria first.
		for (const competencyId of experience.competency_ids) {
			if (body.competency_ids.includes(competencyId)) continue;
			const hasCriteria = liveCriteriaOf(experienceId).some(
				(criterion) => criterion.competency_id === competencyId
			);
			if (hasCriteria) {
				fail(
					409,
					'competency_has_criteria',
					'La competencia todavía tiene criterios: elimínalos primero.'
				);
			}
		}
		experience.competency_ids = [...body.competency_ids];
	}

	if (body.title !== undefined) experience.title = body.title;
	if (body.situation_text !== undefined) {
		experience.situation_text = body.situation_text.trim() === '' ? null : body.situation_text;
	}
	experience.starts_on = startsOn;
	experience.ends_on = endsOn;
	return toExperienceDto(experience);
}

export async function confirmExperience(experienceId: string): Promise<ExperienceDto> {
	await delay();
	const experience = experienceById(experienceId);
	if (!experience) fail(404, 'not_found', 'La experiencia no existe.');
	if (experience.status !== 'borrador') {
		fail(409, 'experience_not_draft', 'La experiencia ya está planificada.');
	}
	experience.status = 'planificada';
	return toExperienceDto(experience);
}

export async function deleteExperience(experienceId: string): Promise<void> {
	await delay();
	const experience = experienceById(experienceId);
	if (!experience) fail(404, 'not_found', 'La experiencia no existe.');
	// Its criteria, evidences and sessions go with it.
	experience.deleted = true;
	for (const criterion of criteria) {
		if (criterion.experience_id === experienceId) criterion.deleted = true;
	}
	for (const evidence of evidences) {
		if (evidence.experience_id === experienceId) evidence.deleted = true;
	}
	for (const entry of sessions) {
		if (entry.experience_id === experienceId) entry.deleted = true;
	}
}

function toCriterionDto(criterion: Criterion): ExperienceCriterionDto {
	return clone({
		id: criterion.id,
		experience_id: criterion.experience_id,
		competency_id: criterion.competency_id,
		description: criterion.description,
		capability_ids: criterion.capability_ids,
		performance_id: criterion.performance_id,
		proposed_by: criterion.proposed_by,
		accepted_at: criterion.accepted_at,
	});
}

export async function createCriterion(
	experienceId: string,
	body: CreateCriterionBody
): Promise<ExperienceCriterionDto> {
	await delay();
	const experience = experienceById(experienceId);
	if (!experience) fail(404, 'not_found', 'La experiencia no existe.');
	requireCriterionBody(experience, body);
	const criterion: Criterion = {
		id: newId(),
		experience_id: experienceId,
		competency_id: body.competency_id,
		description: body.description,
		capability_ids: [...body.capability_ids],
		performance_id: body.performance_id ?? null,
		proposed_by: 'teacher',
		accepted_at: nowISO(),
		deleted: false,
	};
	criteria.push(criterion);
	return toCriterionDto(criterion);
}

export async function updateCriterion(
	criterionId: string,
	body: UpdateCriterionBody
): Promise<ExperienceCriterionDto> {
	await delay();
	const criterion = criterionById(criterionId);
	if (!criterion) fail(404, 'not_found', 'El criterio no existe.');
	const experience = experienceById(criterion.experience_id);
	if (!experience) fail(404, 'not_found', 'La experiencia no existe.');

	if (body.capability_ids !== undefined) {
		if (body.capability_ids.length === 0) {
			fail(422, 'criterion_needs_capability', 'El criterio debe mirar al menos una capacidad.');
		}
		for (const capabilityId of body.capability_ids) {
			const found = capabilityById(capabilityId);
			if (!found || found.competency.id !== criterion.competency_id) {
				fail(
					422,
					'capability_not_in_competency',
					'Una de las capacidades no pertenece a esa competencia.'
				);
			}
		}
		criterion.capability_ids = [...body.capability_ids];
	}
	if (body.performance_id === null) {
		criterion.performance_id = null;
	} else if (body.performance_id !== undefined) {
		const competency = competencyById(criterion.competency_id);
		if (!competency || !competency.performances.some((item) => item.id === body.performance_id)) {
			fail(
				422,
				'performance_not_in_grade',
				'El desempeño no es de esa competencia para el grado de la clase.'
			);
		}
		criterion.performance_id = body.performance_id;
	}
	if (body.description !== undefined) criterion.description = body.description;
	// Editing a proposal also accepts it.
	if (criterion.accepted_at === null) criterion.accepted_at = nowISO();
	return toCriterionDto(criterion);
}

export async function acceptCriterion(criterionId: string): Promise<ExperienceCriterionDto> {
	await delay();
	const criterion = criterionById(criterionId);
	if (!criterion) fail(404, 'not_found', 'El criterio no existe.');
	if (criterion.accepted_at === null) criterion.accepted_at = nowISO();
	return toCriterionDto(criterion);
}

export async function deleteCriterion(criterionId: string): Promise<void> {
	await delay();
	const criterion = criterionById(criterionId);
	if (!criterion) fail(404, 'not_found', 'El criterio no existe.');
	// Also removed from evidences.
	criterion.deleted = true;
	for (const evidence of evidences) {
		evidence.criterion_ids = evidence.criterion_ids.filter((id) => id !== criterionId);
	}
}

// Same rules as the server: a numeric evidence has a maximum above 0 (20 when
// none is named); an ordinal one (AD/A/B/C) has none.
function resolveScale(
	valueScale: ValueScale | undefined,
	maxScore: number | null | undefined
): { value_scale: ValueScale; max_score: number | null } {
	const scale = valueScale ?? 'numeric';
	if (scale === 'ordinal') {
		if (maxScore !== undefined && maxScore !== null) {
			fail(400, 'bad_request', 'Una evidencia con letras (AD/A/B/C) no lleva nota máxima.');
		}
		return { value_scale: scale, max_score: null };
	}
	const max = maxScore ?? 20;
	if (max <= 0) fail(400, 'bad_request', 'La nota máxima debe ser mayor que 0.');
	return { value_scale: scale, max_score: max };
}

function toEvidenceDto(evidence: Evidence): PlannedEvidenceDto {
	return clone({
		id: evidence.id,
		experience_id: evidence.experience_id,
		name: evidence.name,
		kind: evidence.kind,
		value_scale: evidence.value_scale,
		max_score: evidence.max_score,
		criterion_ids: evidence.criterion_ids,
		session_date: evidence.session_date,
		proposed_by: evidence.proposed_by,
		accepted_at: evidence.accepted_at,
	});
}

export async function createEvidence(
	experienceId: string,
	body: CreateEvidenceBody
): Promise<PlannedEvidenceDto> {
	await delay();
	const experience = experienceById(experienceId);
	if (!experience) fail(404, 'not_found', 'La experiencia no existe.');
	if (body.name.trim() === '') {
		fail(400, 'missing_name', 'La evidencia necesita un nombre.');
	}
	requireEvidenceKind(body.kind);
	const scale = resolveScale(body.value_scale, body.max_score);
	requireEvidenceCriteria(experience, body.criterion_ids);
	if (body.session_date !== undefined && body.session_date !== null) {
		requireClassDateIn(experience, body.session_date);
		// Placement needs that date's session entry to exist.
		if (!sessionOf(experienceId, body.session_date)) {
			fail(422, 'date_not_in_experience', 'Esa fecha todavía no tiene sesión.');
		}
	}
	const evidence: Evidence = {
		id: newId(),
		experience_id: experienceId,
		name: body.name,
		kind: body.kind,
		value_scale: scale.value_scale,
		max_score: scale.max_score,
		criterion_ids: [...body.criterion_ids],
		session_date: null,
		proposed_by: 'teacher',
		accepted_at: nowISO(),
		deleted: false,
	};
	evidences.push(evidence);
	if (body.session_date !== undefined && body.session_date !== null) {
		placeEvidence(experience, evidence, body.session_date);
	}
	return toEvidenceDto(evidence);
}

export async function updateEvidence(
	evidenceId: string,
	body: UpdateEvidenceBody
): Promise<PlannedEvidenceDto> {
	await delay();
	const evidence = evidenceById(evidenceId);
	if (!evidence) fail(404, 'not_found', 'La evidencia no existe.');
	const experience = experienceById(evidence.experience_id);
	if (!experience) fail(404, 'not_found', 'La experiencia no existe.');

	if (body.name !== undefined) {
		if (body.name.trim() === '') fail(400, 'missing_name', 'La evidencia necesita un nombre.');
		evidence.name = body.name;
	}
	if (body.kind !== undefined) {
		requireEvidenceKind(body.kind);
		evidence.kind = body.kind;
	}
	if (body.value_scale !== undefined || body.max_score !== undefined) {
		const next = body.value_scale ?? evidence.value_scale;
		// The old maximum belongs to the old scale.
		const max = body.max_score ?? (next === evidence.value_scale ? evidence.max_score : undefined);
		const scale = resolveScale(next, max);
		evidence.value_scale = scale.value_scale;
		evidence.max_score = scale.max_score;
	}
	if (body.criterion_ids !== undefined) {
		requireEvidenceCriteria(experience, body.criterion_ids);
		evidence.criterion_ids = [...body.criterion_ids];
	}
	if (body.session_date !== undefined) {
		if (body.session_date !== null) {
			requireClassDateIn(experience, body.session_date);
			if (!sessionOf(experience.id, body.session_date)) {
				fail(422, 'date_not_in_experience', 'Esa fecha todavía no tiene sesión.');
			}
		}
		placeEvidence(experience, evidence, body.session_date);
	}
	// Editing a proposal also accepts it.
	if (evidence.accepted_at === null) evidence.accepted_at = nowISO();
	return toEvidenceDto(evidence);
}

export async function acceptEvidence(evidenceId: string): Promise<PlannedEvidenceDto> {
	await delay();
	const evidence = evidenceById(evidenceId);
	if (!evidence) fail(404, 'not_found', 'La evidencia no existe.');
	if (evidence.accepted_at === null) evidence.accepted_at = nowISO();
	return toEvidenceDto(evidence);
}

export async function deleteEvidence(evidenceId: string): Promise<void> {
	await delay();
	const evidence = evidenceById(evidenceId);
	if (!evidence) fail(404, 'not_found', 'La evidencia no existe.');
	evidence.deleted = true;
	// Its session entry keeps existing, without the evidencia placed on it.
	for (const entry of sessions) {
		if (entry.planned_evidence_id === evidenceId) entry.planned_evidence_id = null;
	}
}

function toSessionDto(entry: SessionEntry): SessionOutlineDto {
	return clone({
		date: entry.date,
		title: entry.title,
		topics: entry.topics,
		planned_evidence_id: entry.planned_evidence_id,
		proposed_by: entry.proposed_by,
		accepted_at: entry.accepted_at,
	});
}

export async function updateSession(
	experienceId: string,
	date: string,
	body: UpdateSessionBody
): Promise<SessionOutlineDto> {
	await delay();
	const experience = experienceById(experienceId);
	if (!experience) fail(404, 'not_found', 'La experiencia no existe.');
	requireClassDateIn(experience, date);
	if (body.title.trim() === '') {
		fail(400, 'missing_title', 'La sesión necesita un título.');
	}
	if (body.planned_evidence_id !== undefined && body.planned_evidence_id !== null) {
		const evidence = evidenceById(body.planned_evidence_id);
		if (!evidence || evidence.experience_id !== experienceId) {
			fail(404, 'not_found', 'La evidencia no existe.');
		}
	}

	// Creates or replaces that date's entry, and accepts it.
	let entry = sessionOf(experienceId, date);
	if (!entry) {
		entry = {
			experience_id: experienceId,
			date: date,
			title: body.title,
			topics: body.topics ?? null,
			planned_evidence_id: null,
			proposed_by: 'teacher',
			accepted_at: null,
			deleted: false,
		};
		sessions.push(entry);
	} else {
		entry.title = body.title;
		entry.topics = body.topics ?? null;
	}
	entry.accepted_at = nowISO();

	// The other side of the placement relation.
	if (body.planned_evidence_id !== undefined) {
		const evidence =
			body.planned_evidence_id === null ? null : evidenceById(body.planned_evidence_id);
		if (evidence) placeEvidence(experience, evidence, date);
		else entry.planned_evidence_id = null;
	}
	return toSessionDto(entry);
}

export async function acceptSession(
	experienceId: string,
	date: string
): Promise<SessionOutlineDto> {
	await delay();
	const entry = sessionOf(experienceId, date);
	if (!entry) fail(404, 'not_found', 'Esa fecha no tiene sesión.');
	if (entry.accepted_at === null) entry.accepted_at = nowISO();
	return toSessionDto(entry);
}

export async function deleteSession(experienceId: string, date: string): Promise<void> {
	await delay();
	const entry = sessionOf(experienceId, date);
	if (!entry) fail(404, 'not_found', 'Esa fecha no tiene sesión.');
	entry.deleted = true;
	// A placed evidencia stays, unplaced.
	for (const evidence of evidences) {
		if (evidence.id === entry.planned_evidence_id) evidence.session_date = null;
	}
	entry.planned_evidence_id = null;
}

// ---------- generate with Mawta ----------

export async function proposeExperience(
	_classId: string,
	body: ExperienceProposalBody
): Promise<GenerationDto> {
	await delay();
	if (body.term_id !== TERM.id) fail(404, 'not_found', 'El periodo no existe.');
	if (body.idea_text.trim() === '') {
		fail(400, 'missing_idea', 'Cuéntale a Mawta tu idea.');
	}
	let competencyIds = body.competency_ids ?? [];
	if (competencyIds.length > 0) {
		requireCompetencies(competencyIds);
	} else {
		// The agent detects the competencias from the idea.
		competencyIds = IDEA_KEYWORDS.filter((entry) => entry.match.test(body.idea_text)).map(
			(entry) => entry.competency_id
		);
		if (competencyIds.length === 0) competencyIds = ['mat-c1'];
	}
	const chosen = competencyIds;

	const generation = startGeneration('experience', null, null, () => {
		const titled = PROPOSAL_TITLES.find((entry) => entry.match.test(body.idea_text));
		const primary = competencyById(chosen[0] ?? '');
		const dates = proposalDates();
		return {
			proposal: {
				title: titled?.title ?? 'Nuestra experiencia de aprendizaje',
				situation_text:
					(primary !== undefined ? PROPOSAL_SITUATIONS[primary.id] : undefined) ??
					'Vivimos una situación de la vida del aula en la que la matemática nos ayuda a decidir.',
				competency_ids: [...chosen],
				starts_on: dates.starts_on,
				ends_on: dates.ends_on,
			},
		};
	});
	return toGenerationDto(generation);
}

export async function generateCriteria(
	experienceId: string,
	competencyId: string
): Promise<GenerationDto> {
	await delay();
	const experience = experienceById(experienceId);
	if (!experience) fail(404, 'not_found', 'La experiencia no existe.');
	const competency = competencyById(competencyId);
	if (!competency) {
		fail(422, 'competency_not_in_subject', 'La competencia no pertenece al área de la clase.');
	}
	if (!experience.competency_ids.includes(competencyId)) {
		fail(422, 'competency_not_in_subject', 'La competencia no es parte de la experiencia.');
	}

	const generation = startGeneration('criteria', experienceId, competencyId, () => {
		// Only the capabilities without a criterio get one.
		const covered = coveredCapabilities(experienceId, competencyId, false);
		const inserted: string[] = [];
		for (const capability of competency.capabilities) {
			if (covered.has(capability.id)) continue;
			const bank = CRITERIA_BANK[capability.id];
			if (!bank) continue;
			const criterion: Criterion = {
				id: newId(),
				experience_id: experienceId,
				competency_id: competencyId,
				description: bank.text,
				capability_ids: [capability.id],
				performance_id: null,
				proposed_by: 'mawta',
				accepted_at: null,
				deleted: false,
			};
			criteria.push(criterion);
			inserted.push(criterion.id);
		}
		return { criteria_ids: inserted };
	});
	return toGenerationDto(generation);
}

export async function generateEvidences(experienceId: string): Promise<GenerationDto> {
	await delay();
	const experience = experienceById(experienceId);
	if (!experience) fail(404, 'not_found', 'La experiencia no existe.');

	const generation = startGeneration('evidences', experienceId, null, () => {
		const own = liveCriteriaOf(experienceId);
		if (own.length === 0) {
			throw new Error('La experiencia todavía no tiene criterios.');
		}
		const observed = new Set(
			liveEvidencesOf(experienceId).flatMap((evidence) => evidence.criterion_ids)
		);
		const existing = new Set(liveEvidencesOf(experienceId).map((evidence) => evidence.name));
		const inserted: string[] = [];
		for (const competencyId of experience.competency_ids) {
			const bank = EVIDENCE_BANK[competencyId];
			if (!bank || existing.has(bank.name)) continue;
			const unobserved = own
				.filter((criterion) => criterion.competency_id === competencyId)
				.filter((criterion) => !observed.has(criterion.id))
				.map((criterion) => criterion.id);
			if (unobserved.length === 0) continue;
			const evidence: Evidence = {
				id: newId(),
				experience_id: experienceId,
				name: bank.name,
				kind: bank.kind,
				value_scale: 'numeric',
				max_score: 20,
				criterion_ids: unobserved,
				session_date: null,
				proposed_by: 'mawta',
				accepted_at: null,
				deleted: false,
			};
			evidences.push(evidence);
			inserted.push(evidence.id);
		}
		return { evidence_ids: inserted };
	});
	return toGenerationDto(generation);
}

export async function generateSessions(experienceId: string): Promise<GenerationDto> {
	await delay();
	const experience = experienceById(experienceId);
	if (!experience) fail(404, 'not_found', 'La experiencia no existe.');

	const generation = startGeneration('sessions', experienceId, null, () => {
		// Only the class dates without an entry get one.
		const taken = new Set(liveSessionsOf(experienceId).map((entry) => entry.date));
		const empty = classDatesBetween(experience.starts_on, experience.ends_on).filter(
			(date) => !taken.has(date)
		);
		const inserted: string[] = [];
		empty.forEach((date, index) => {
			const entry: SessionEntry = {
				experience_id: experienceId,
				date: date,
				title: SESSION_TITLES[index % SESSION_TITLES.length] ?? 'Practicamos y repasamos',
				topics: 'sesión de la experiencia',
				planned_evidence_id: null,
				proposed_by: 'mawta',
				accepted_at: null,
				deleted: false,
			};
			sessions.push(entry);
			inserted.push(date);
		});
		return { session_dates: inserted };
	});
	return toGenerationDto(generation);
}

export async function getGeneration(generationId: string): Promise<GenerationDto> {
	await delay();
	const generation = generations.get(generationId);
	if (!generation) fail(404, 'not_found', 'La generación no existe.');
	return toGenerationDto(generation);
}
