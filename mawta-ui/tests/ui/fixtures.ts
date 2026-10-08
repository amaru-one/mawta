import { test as base, expect, type Page } from '@playwright/test';
import type {
	ExperienceDto,
	EvaluationDto,
	CompetencyLevelDto,
	NotificationDto,
} from '../../src/lib/api/dto';

export const competency = { id: 'comp-1', code: 'MAT-1', name: 'Resuelve problemas de cantidad' };
export const dates = ['2026-10-05', '2026-10-07', '2026-10-09'];
const timestamp = '2026-10-06T14:00:00Z';
export const studentRoute = '/class/class-1/students/student-1?name=Ana%20Quispe&course=Matemática';
export const planningBase = '/class/class-1/plan/experience-1';
export const routeCases = [
	['/', 'Mawta — Inicio', 'Matemática'],
	['/login', 'Iniciar sesión', 'Ingresar'],
	['/profile', 'Mi perfil', 'María Santos'],
	['/notifications', 'Notificaciones', 'Revisa los avances'],
	['/class/class-1', 'Matemática — Panel', 'Alumnos'],
	['/class/class-1/criteria', 'Criterios de evaluación', competency.name],
	['/class/class-1/evidence/new', 'Nueva evidencia — Clase', 'Guardar evidencia'],
	['/class/class-1/lesson/session-1', 'Matemática — Lección', 'La tiendita escolar'],
	['/class/class-1/students', 'Alumnos — Matemática', 'Quispe, Ana'],
	[studentRoute, 'Ana Quispe — Matemática', 'Nivel de logro'],
	['/class/class-1/plan', 'Tu trimestre', 'La tiendita escolar'],
	['/class/class-1/plan/new', 'Nueva experiencia', '¿Qué tienes en mente?'],
	[`${planningBase}/criteria`, 'Criterios', competency.name],
	[`${planningBase}/evidences`, 'Evidencias', 'Lista de precios'],
	[`${planningBase}/sessions`, 'Sesiones', 'Organizamos la tienda'],
	[`${planningBase}/summary`, 'Revisar y guardar', 'Guardar experiencia'],
] as const;

export function seed() {
	const experience: ExperienceDto = {
		id: 'experience-1',
		class_id: 'class-1',
		term_id: 'term-1',
		status: 'borrador',
		title: 'La tiendita escolar',
		idea_text: 'Organizar una tienda en el aula',
		situation_text: 'Calculamos los precios y explicamos nuestras decisiones.',
		starts_on: dates[0],
		ends_on: dates[2],
		competencies: [competency],
		criteria: [
			{
				id: 'criterion-1',
				experience_id: 'experience-1',
				competency_id: 'comp-1',
				description: 'Explica cómo calcula el cambio de una compra.',
				capability_ids: ['cap-1'],
				performance_id: 'performance-1',
				proposed_by: 'mawta',
				accepted_at: null,
			},
		],
		evidences: [
			{
				id: 'evidence-1',
				experience_id: 'experience-1',
				name: 'Lista de precios',
				kind: 'produccion',
				value_scale: 'numeric',
				max_score: 20,
				criterion_ids: ['criterion-1'],
				session_date: null,
				proposed_by: 'mawta',
				accepted_at: null,
			},
		],
		sessions: [
			{
				date: dates[0],
				title: 'Organizamos la tienda',
				topics: 'Sumas y restas',
				planned_evidence_id: null,
				proposed_by: 'mawta',
				accepted_at: null,
			},
		],
		class_dates: dates,
		warnings: [{ code: 'pending_proposals', count: 3 }],
	};
	const evaluations: EvaluationDto[] = [
		{
			assessment_id: 'numeric-1',
			title: 'Problemas de compras',
			kind: 'practica',
			value_scale: 'numeric',
			max_score: 20,
			due_at: null,
			is_personal: false,
			criteria: [
				{
					criterion_id: 'criterion-1',
					code: 'CR1',
					description: 'Explica cómo calcula el cambio.',
				},
			],
			score: null,
		},
		{
			assessment_id: 'ordinal-1',
			title: 'Explicación de estrategias',
			kind: 'exposicion',
			value_scale: 'ordinal',
			max_score: null,
			due_at: null,
			is_personal: false,
			criteria: [
				{
					criterion_id: 'criterion-1',
					code: 'CR1',
					description: 'Explica cómo calcula el cambio.',
				},
			],
			score: null,
		},
	];
	const levels: CompetencyLevelDto[] = [
		{
			competency_id: 'comp-1',
			code: 'MAT-1',
			name: competency.name,
			kind: 'area',
			level: null,
			asserted_at: null,
			conclusion_required: false,
			conclusion_requirement: 'optional',
			conclusion_body: null,
			conclusion_status: null,
		},
	];
	const notifications: NotificationDto[] = [
		{
			id: 'notification-1',
			kind: 'alert',
			category: 'trend',
			title: 'Revisa los avances',
			body: 'Revisa los avances de esta semana.',
			created_at: timestamp,
			read_at: null,
			student_name: 'Ana Quispe',
			class_name: 'Matemática',
		},
	];
	return {
		experience,
		evaluations,
		levels,
		notifications,
		unavailable: false,
		loginError: false,
		failures: new Set<string>(),
		writes: [] as { method: string; path: string; body: Record<string, unknown> }[],
		unexpected: [] as string[],
	};
}
export type ApiState = ReturnType<typeof seed>;

export async function mockApi(page: Page, state: ApiState) {
	await page.route('https://fonts.googleapis.com/**', (route) => route.abort());
	await page.route('https://fonts.gstatic.com/**', (route) => route.abort());
	await page.route('**/api/v1/**', async (route) => {
		const request = route.request(),
			url = new URL(request.url()),
			path = url.pathname.replace('/api/v1', ''),
			method = request.method();
		const send = (body: unknown, status = 200) =>
			route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
		if (state.failures.has(path))
			return send({ error: { code: 'unavailable', message: 'No disponible' } }, 503);
		const me = {
			role: 'teacher',
			user: { display_name: 'María Santos', email: 'teacher@example.test' },
			teacher: { id: 'teacher-1', title: 'Docente' },
			tenant: {
				id: 'school-1',
				name: 'Colegio San Felipe',
				city: 'Lima',
				timezone: 'America/Lima',
			},
		};
		const classCriteria = {
			competencies: [
				{
					competency_id: 'comp-1',
					code: 'MAT-1',
					name: competency.name,
					kind: 'area',
					criteria: [
						{
							criterion_id: 'criterion-1',
							code: 'CR1',
							description: 'Explica cómo calcula el cambio.',
						},
					],
				},
			],
		};
		const curriculum = {
			grade: { code: '1SEC', cycle: 'VI', expected_level: 6 },
			competencies: [
				{
					...competency,
					kind: 'area',
					capabilities: [
						{ id: 'cap-1', code: 'C1', name: 'Traduce cantidades' },
						{ id: 'cap-2', code: 'C2', name: 'Argumenta afirmaciones' },
					],
					performances: [
						{
							id: 'performance-1',
							order: 1,
							text: 'Establece relaciones entre cantidades y las transforma en expresiones numéricas.',
							en_proceso: false,
							suggested_capability_id: 'cap-1',
						},
					],
				},
			],
		};
		if (method !== 'GET') {
			const body = request.headers()['content-type']?.includes('application/json')
				? (request.postDataJSON() as Record<string, unknown>)
				: {
						duration_ms: Number(
							request.postData()?.match(/name="duration_ms"\r\n\r\n(\d+)/)?.[1] ?? 0
						),
					};
			state.writes.push({ method, path, body });
			if (path === '/auth/login')
				return state.loginError
					? send({ error: { code: 'invalid_credentials', message: 'Invalid credentials' } }, 401)
					: send(me);
			if (path === '/auth/logout') return send({ ok: true });
			if (path === '/notifications/read-all') {
				state.notifications.forEach((n) => (n.read_at = timestamp));
				return send({ marked_read: 1 });
			}
			if (/\/notifications\/.*\/read$/.test(path)) {
				state.notifications.forEach((n) => (n.read_at = timestamp));
				return send({ ok: true });
			}
			if (path.endsWith('/competency-levels')) {
				Object.assign(state.levels[0], {
					level: body.level,
					conclusion_required: body.level === 'C',
					conclusion_requirement: body.level === 'C' ? 'level_c' : 'optional',
				});
				return send({ id: 'level-1', level: body.level });
			}
			if (path.endsWith('/conclusions')) {
				Object.assign(state.levels[0], {
					conclusion_body: body.body,
					conclusion_status: body.status,
				});
				return send({ id: 'conclusion-1', status: body.status });
			}
			if (/\/assessments\/.*\/scores$/.test(path) || path.startsWith('/scores/')) {
				const ev = state.evaluations.find(
					(e) => path.includes(e.assessment_id) || path.includes(e.score?.score_id ?? '-')
				);
				if (ev) {
					const raw = body.raw_value == null ? null : Number(body.raw_value);
					ev.score = {
						score_id: `score-${ev.assessment_id}`,
						status: (body.status ?? 'graded') as 'graded',
						raw_value: raw,
						percentage: raw !== null && ev.max_score ? (raw / ev.max_score) * 100 : null,
						level: (body.level as 'A') ?? null,
					};
				}
				return send({ id: ev ? `score-${ev.assessment_id}` : 'score-1' });
			}
			if (path.endsWith('/experience-proposals') || path.endsWith('/generate'))
				return state.unavailable
					? send({ error: { code: 'agent_unavailable', message: 'Agent unavailable' } }, 503)
					: send({
							id: 'generation-1',
							kind: 'experience',
							status: 'pending',
							result: null,
							error: null,
						});
			if (path === '/classes/class-1/experiences') {
				Object.assign(state.experience, body, { competencies: [competency] });
				return send(state.experience);
			}
			if (path.endsWith('/confirm')) {
				state.experience.status = 'planificada';
				return send(state.experience);
			}
			if (path.startsWith('/criteria/')) {
				const item = state.experience.criteria?.find((c) => path.includes(c.id));
				if (path.endsWith('/delete'))
					state.experience.criteria = state.experience.criteria?.filter((c) => c !== item) ?? [];
				else if (item)
					Object.assign(item, body, { accepted_at: timestamp, proposed_by: 'teacher' });
				return send(item ?? {});
			}
			if (path === '/experiences/experience-1/criteria') {
				const item = {
					id: 'criterion-new',
					experience_id: 'experience-1',
					competency_id: String(body.competency_id),
					description: String(body.description),
					capability_ids: body.capability_ids as string[],
					performance_id: String(body.performance_id),
					proposed_by: 'teacher',
					accepted_at: timestamp,
				};
				state.experience.criteria?.push(item);
				return send(item);
			}
			if (path.startsWith('/evidences/')) {
				const item = state.experience.evidences?.find((e) => path.includes(e.id));
				if (path.endsWith('/delete'))
					state.experience.evidences = state.experience.evidences?.filter((e) => e !== item) ?? [];
				else if (item)
					Object.assign(item, body, { accepted_at: timestamp, proposed_by: 'teacher' });
				return send(item ?? {});
			}
			if (path === '/experiences/experience-1/evidences') {
				const item = {
					id: `evidence-new-${state.writes.length}`,
					experience_id: 'experience-1',
					name: String(body.name),
					kind: body.kind as 'produccion',
					value_scale: (body.value_scale ?? 'numeric') as 'numeric',
					max_score: body.value_scale === 'ordinal' ? null : Number(body.max_score ?? 20),
					criterion_ids: body.criterion_ids as string[],
					session_date: null,
					proposed_by: 'teacher',
					accepted_at: timestamp,
				};
				state.experience.evidences?.push(item);
				return send(item);
			}
			if (path.startsWith('/experiences/experience-1/sessions/')) {
				const date = path.split('/')[4],
					previous = state.experience.sessions?.find((s) => s.date === date);
				if (path.endsWith('/delete')) {
					state.experience.sessions =
						state.experience.sessions?.filter((s) => s.date !== date) ?? [];
					return send({});
				}
				if (path.endsWith('/accept') && previous) {
					previous.accepted_at = timestamp;
					return send(previous);
				}
				const item = {
					date,
					title: String(body.title),
					topics: (body.topics as string) ?? null,
					planned_evidence_id: (body.planned_evidence_id as string) ?? null,
					proposed_by: 'teacher',
					accepted_at: timestamp,
				};
				state.experience.sessions = [
					...(state.experience.sessions ?? []).filter((s) => s.date !== date),
					item,
				];
				return send(item);
			}
			if (path.endsWith('/voice-notes')) return send({ id: 'voice-new' });
			if (path.startsWith('/voice-notes/'))
				return send({ status: path.endsWith('/discard') ? 'discarded' : 'saved' });
			if (path.endsWith('/assessments')) return send({ id: 'new-1' });
			if (path.endsWith('/delete') || path.endsWith('/start'))
				return send({ status: 'in_progress' });
			state.unexpected.push(method + ' ' + path);
			return send({ error: { code: 'unmocked', message: path } }, 500);
		}
		if (path === '/me') return send(me);
		if (path === '/home')
			return send({
				date: '2026-10-06',
				today: [
					{
						class_id: 'class-1',
						name: 'Matemática',
						session_id: 'session-1',
						scheduled_start_at: '2026-10-06T14:00:00Z',
						scheduled_end_at: '2026-10-06T15:00:00Z',
						status: 'scheduled',
						room: 'Aula 1',
						topic: 'La tiendita escolar',
					},
				],
				week: [
					{
						date: '2026-10-07',
						weekday: 3,
						sessions: [
							{
								class_id: 'class-1',
								name: 'Matemática',
								session_id: 'session-2',
								scheduled_start_at: '2026-10-07T14:00:00Z',
								scheduled_end_at: '2026-10-07T15:00:00Z',
								status: 'cancelled',
								room: 'Aula 1',
								topic: 'Compras',
							},
						],
					},
				],
			});
		if (path === '/notifications') return send({ notifications: state.notifications });
		if (path === '/profile')
			return send({
				display_name: 'María Santos',
				title: 'Docente de Matemática',
				hired_on: '2020-03-01',
				tenant_name: 'Colegio San Felipe',
				tenant_city: 'Lima',
				top_stats: { classes: 1, students: 2, weekly_hours: 6 },
				activity: {
					clases_dictadas: 10,
					asistencias_registradas: 20,
					asistencias_esperadas: 20,
					notas_de_voz: 2,
					evaluaciones: 2,
				},
				classes_by_grade: [
					{
						grade_label: 'Primero de secundaria',
						classes: [
							{ class_id: 'class-1', name: 'Matemática', roster_count: 2, slots_per_week: 3 },
						],
					},
				],
			});
		if (path.endsWith('/dashboard'))
			return send({
				class_id: 'class-1',
				name: 'Matemática',
				roster_count: 2,
				sessions_per_week: 3,
				term_id: 'term-1',
				next_session: {
					session_id: 'session-1',
					session_date: '2026-10-06',
					scheduled_start_at: '2026-10-06T14:00:00Z',
					scheduled_end_at: '2026-10-06T15:00:00Z',
					topic: 'La tiendita escolar',
					status: 'scheduled',
				},
				stats: { scored: 0, expected: 2, asistencia_pct: 100 },
				distribution: [],
				grades_pending: [],
				attendance_unmarked: [],
				upcoming: [],
				past: [],
			});
		if (path === '/classes/class-1/criteria') return send(classCriteria);
		if (path === '/classes/class-1/students')
			return send({
				students: [
					{
						student_id: 'student-1',
						full_name: 'Quispe, Ana',
						level: state.levels[0].level,
						evidence_count: 2,
					},
					{ student_id: 'student-2', full_name: 'Santos, Luis', level: 'A', evidence_count: 1 },
				],
			});
		if (path.endsWith('/competencies')) return send({ competencies: state.levels });
		if (path.endsWith('/evidence')) return send({ evidence: state.evaluations });
		if (path === '/sessions/session-1')
			return send({
				header: {
					session_id: 'session-1',
					class_id: 'class-1',
					class_name: 'Matemática',
					term_id: 'term-1',
					topic: 'La tiendita escolar',
					session_date: '2026-10-06',
					status: 'in_progress',
				},
				roster: [
					{ student_id: 'student-1', name: 'Ana Quispe', voice_notes: [] },
					{ student_id: 'student-2', name: 'Luis Santos', voice_notes: [] },
				],
			});
		if (path.endsWith('/curriculum')) return send(curriculum);
		if (path.endsWith('/calendar'))
			return send({
				class_dates: [...dates, '2026-10-12', '2026-10-14', '2026-10-16'],
				non_teaching_days: [],
			});
		if (path === '/experiences/experience-1') return send(state.experience);
		if (path.endsWith('/plan'))
			return send({
				term: {
					id: 'term-1',
					name: 'Tercer trimestre',
					starts_on: '2026-10-01',
					ends_on: '2026-12-18',
					status: 'active',
				},
				non_teaching_days: [
					{ from: '2026-10-08', to: '2026-10-08', kind: 'feriado', label: 'Feriado' },
				],
				class_dates_total: 30,
				experiences: [
					{
						id: 'experience-1',
						title: state.experience.title,
						status: state.experience.status,
						starts_on: dates[0],
						ends_on: dates[2],
						class_dates: 3,
						competencies: [{ ...competency, capabilities_total: 2, capabilities_with_criteria: 1 }],
						pending_proposals: 3,
					},
				],
				competencies: [
					{
						...competency,
						status: 'toca',
						terms_worked: [1],
						capabilities_total: 2,
						capabilities_covered_this_term: 0,
					},
				],
			});
		if (path === '/generations/generation-1')
			return send({
				id: 'generation-1',
				kind: 'experience',
				status: 'completed',
				error: null,
				result: {
					proposal: {
						title: 'La feria del aula',
						situation_text: 'Calculamos y explicamos los precios.',
						competency_ids: ['comp-1'],
						starts_on: '2026-10-12',
						ends_on: '2026-10-16',
					},
				},
			});
		state.unexpected.push(method + ' ' + path);
		return send({ error: { code: 'unmocked', message: path } }, 500);
	});
}
export const test = base.extend<{ api: ApiState }>({
	api: async ({ page }, use) => {
		const state = seed();
		await mockApi(page, state);
		await use(state);
		expect(state.unexpected).toEqual([]);
	},
});
export { expect };
