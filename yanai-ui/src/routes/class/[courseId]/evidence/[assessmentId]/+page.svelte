<script lang="ts">
	// The evidencia × criterio grid for one piece of evidence, across the whole
	// class: criterios down, students across, a level in each cell.
	//
	// This is how a teacher actually marks — one criterio at a time down thirty
	// scripts, rather than opening thirty student screens. It is the class-wide
	// half of the same capture the student's screen offers per evidence; both
	// write the same rows.
	//
	// There is no mark here, deliberately. The school's numeric system is the
	// *other* reading of this same evidence and lives on the student's screen.
	// A /20 box beside these pickers would put a number in the teacher's eye at
	// the exact moment they are meant to be judging against a criterio, which is
	// the one adjacency RVM 094-2020's framing argues against.
	import { onMount } from 'svelte';
	import { page } from '$app/state';
	import { ApiError, list } from '$lib/api/client';
	import type { AssessmentCriteriaGridDto } from '$lib/api/dto';
	import { assertCriterionLevel, getAssessmentCriteriaGrid } from '$lib/api/endpoints/criteria';
	import LevelPicker from '$lib/components/LevelPicker.svelte';
	import TopBar from '$lib/components/TopBar.svelte';
	import type { Tier } from '$lib/grades';
	import { hapticTap } from '$lib/haptics';
	import { showToast } from '$lib/toast';

	const courseId = $derived(page.params.courseId ?? '');
	const assessmentId = $derived(page.params.assessmentId ?? '');
	const courseName = $derived(page.url.searchParams.get('course') ?? '');

	let ready = $state(false);
	let loadError = $state(false);
	let grid = $state<AssessmentCriteriaGridDto | null>(null);
	// Keyed `${studentId}:${criterionId}` so one saving cell never freezes the
	// rest — the teacher taps down a column quickly.
	let saving = $state<Set<string>>(new Set());

	async function load(): Promise<void> {
		ready = false;
		loadError = false;
		try {
			grid = await getAssessmentCriteriaGrid(assessmentId);
			ready = true;
		} catch {
			loadError = true;
		}
	}

	onMount(load);

	const criteria = $derived(list(grid?.criteria));
	const students = $derived(list(grid?.students));

	const dateFmt = new Intl.DateTimeFormat('es-PE', {
		day: 'numeric',
		month: 'long'
	});

	const dueLabel = $derived(
		grid?.due_at ? `Entrega ${dateFmt.format(new Date(grid.due_at))}` : 'Sin fecha de entrega'
	);

	function judgedCount(criterionId: string): number {
		return students.filter((s) => s.levels[criterionId] !== undefined).length;
	}

	async function setLevel(studentId: string, criterionId: string, level: Tier): Promise<void> {
		const key = `${studentId}:${criterionId}`;
		if (saving.has(key)) return;
		hapticTap();
		saving = new Set(saving).add(key);
		try {
			await assertCriterionLevel(courseId, studentId, {
				criterion_id: criterionId,
				assessment_id: assessmentId,
				level
			});
			// Patch in place rather than refetching: a full reload on every tap
			// would make marking a class feel like waiting on a network.
			if (grid) {
				grid = {
					...grid,
					students: students.map((s) =>
						s.student_id === studentId
							? { ...s, levels: { ...s.levels, [criterionId]: level } }
							: s
					)
				};
			}
		} catch (err) {
			showToast(err instanceof ApiError ? err.message : 'No se pudo guardar — revisa tu conexión');
		} finally {
			const next = new Set(saving);
			next.delete(key);
			saving = next;
		}
	}
</script>

<TopBar back={`/class/${courseId}`} useHistory />

<div class="body">
	{#if ready && grid}
		<p class="title">{grid.title}</p>
		<p class="subtitle">{courseName} · {dueLabel}</p>

		<p class="intro">
			Valora esta evidencia contra cada criterio. El nivel de logro de la
			competencia no sale de aquí: lo asignas tú al cierre, leyendo todas las
			evidencias del periodo (RVM 094-2020, 5.1.1.3 p.3).
		</p>

		{#if grid.is_personal}
			<p class="intro personal">
				Evidencia personal: solo aplica al alumno para el que se creó.
			</p>
		{/if}

		{#if criteria.length === 0}
			<p class="empty">
				Esta evidencia no declara ningún criterio, así que no hay contra qué
				valorarla. Añádele criterios al crearla, o registra otra.
			</p>
		{:else}
			<div class="stack">
				{#each criteria as c (c.criterion_id)}
					<div class="card crit">
						<p class="crit-name">{c.code ? `${c.code} · ` : ''}{c.description}</p>
						<p class="crit-comp">
							{c.competency_name} · {judgedCount(c.criterion_id)}/{students.length} valorados
						</p>

						{#each students as s (s.student_id)}
							<div class="row student">
								<p class="grow student-name">{s.full_name}</p>
								<LevelPicker
									level={s.levels[c.criterion_id] ?? null}
									disabled={saving.has(`${s.student_id}:${c.criterion_id}`)}
									size={26}
									onselect={(level) => void setLevel(s.student_id, c.criterion_id, level)}
								/>
							</div>
						{/each}

						{#if students.length === 0}
							<p class="empty">No hay alumnos en la lista para esta evidencia.</p>
						{/if}
					</div>
				{/each}
			</div>
		{/if}
	{:else if loadError}
		<p class="empty">No se pudo cargar la evidencia.</p>
	{/if}
</div>

<style>
	.title {
		margin: 0;
		font-size: 20px;
		font-weight: 500;
	}

	.subtitle {
		margin: 2px 0 var(--space-md);
		font-size: 13px;
		color: var(--text-secondary);
	}

	.intro {
		margin: 0 0 var(--space-md);
		font-size: 12px;
		line-height: 1.45;
		color: var(--text-muted);
	}

	.personal {
		color: var(--text-secondary);
	}

	.crit {
		padding: var(--space-md);
	}

	.crit-name {
		margin: 0;
		font-size: 14px;
		font-weight: 500;
		line-height: 1.35;
		color: var(--text-primary);
	}

	.crit-comp {
		margin: 2px 0 var(--space-sm);
		font-size: 11px;
		color: var(--text-muted);
	}

	/* The app's overflow idiom: the name wraps freely beside a fixed-width
	   picker, no ellipsis, top-aligned so a two-line name still reads. */
	.student {
		align-items: flex-start;
		gap: var(--space-md);
		padding: var(--space-sm) 0;
		border-top: 0.5px solid var(--border-subtle, var(--border-strong));
	}

	.student-name {
		margin: 0;
		font-size: 13px;
		line-height: 1.35;
		color: var(--text-primary);
	}

	.empty {
		margin: var(--space-sm) 0 0;
		font-size: 12px;
		color: var(--text-muted);
	}
</style>
