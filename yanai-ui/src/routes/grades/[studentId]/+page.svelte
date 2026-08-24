<script lang="ts">
	import { onMount } from 'svelte';
	import { page } from '$app/state';
	import { ApiError, list } from '$lib/api/client';
	import type { AttemptDto, EvaluationDto, PracticeScoreCreateDto, StudentGradesDto } from '$lib/api/dto';
	import {
		correctScore,
		createPracticeScore,
		createScore,
		deletePracticeScore,
		getStudentGrades,
		requestSummary
	} from '$lib/api/endpoints/grades';
	import AddPracticeScoreDialog from '$lib/components/AddPracticeScoreDialog.svelte';
	import AiSummaryCard from '$lib/components/AiSummaryCard.svelte';
	import ConfirmDialog from '$lib/components/ConfirmDialog.svelte';
	import Icon from '$lib/components/Icon.svelte';
	import TopBar from '$lib/components/TopBar.svelte';
	import { hapticTap } from '$lib/haptics';
	import { showToast } from '$lib/toast';

	const studentId = $derived(page.params.studentId ?? '');
	// Class id and display names travel as query params — the grades endpoint
	// doesn't return them, and the SPA has no other student lookup.
	const classId = $derived(page.url.searchParams.get('class') ?? '');
	const studentName = $derived(page.url.searchParams.get('name') ?? 'Alumno');
	const courseName = $derived(page.url.searchParams.get('course') ?? '');

	let ready = $state(false);
	let loadError = $state(false);
	let data = $state<StudentGradesDto | null>(null);

	async function load(): Promise<void> {
		ready = false;
		loadError = false;
		try {
			data = await getStudentGrades(classId, studentId);
			ready = true;
		} catch {
			loadError = true;
		}
	}

	// Quiet refresh that keeps the screen up — used after writes, once the
	// worker has had time (~2s poll) to recompute the grade.
	async function reload(): Promise<void> {
		try {
			data = await getStudentGrades(classId, studentId);
		} catch {
			// keep showing the last good data
		}
	}

	function reloadSoon(): void {
		setTimeout(() => void reload(), 3000);
	}

	onMount(load);

	const evaluations = $derived(list(data?.evaluations));
	const practiceScores = $derived(list(data?.practice_scores));

	type EvaluationModule = {
		code: string;
		label: string;
		weight: number;
		evaluations: EvaluationDto[];
	};

	const componentLabels: Record<string, string> = {
		listening: 'Listening',
		reading: 'Reading',
		writing: 'Writing',
		speaking: 'Speaking',
		quiz: 'Quiz',
		examen_final: 'Examen final',
		participacion: 'Participación',
		practicas: 'Prácticas calificadas',
		examenes: 'Exámenes',
		actitudinal: 'Actitudinal'
	};

	function moduleLabel(code: string): string {
		return componentLabels[code] ?? code.charAt(0).toUpperCase() + code.slice(1);
	}

	// Groups the flat evaluation list into one accordion section per grading
	// component (Listening, Reading, ...), in the order each first appears.
	const evaluationModules = $derived.by((): EvaluationModule[] => {
		const byCode = new Map<string, EvaluationModule>();
		for (const ev of evaluations) {
			let mod = byCode.get(ev.component_code);
			if (!mod) {
				mod = { code: ev.component_code, label: moduleLabel(ev.component_code), weight: ev.weight, evaluations: [] };
				byCode.set(ev.component_code, mod);
			}
			mod.evaluations.push(ev);
		}
		return [...byCode.values()];
	});

	let expandedModules = $state<Set<string>>(new Set());

	function toggleModule(code: string): void {
		hapticTap();
		const next = new Set(expandedModules);
		if (next.has(code)) {
			next.delete(code);
		} else {
			next.add(code);
		}
		expandedModules = next;
	}

	function scoredCount(mod: EvaluationModule): number {
		return mod.evaluations.filter((ev) => latestAttempt(ev)?.raw_value != null).length;
	}

	const kindLabels: Record<string, string> = {
		quiz: 'Quiz',
		examen: 'Examen',
		practica: 'Práctica',
		tarea: 'Tarea',
		proyecto: 'Proyecto',
		exposicion: 'Exposición',
		participacion: 'Participación',
		rubrica: 'Rúbrica',
		otro: 'Otro'
	};

	function formatNoteDate(iso: string): string {
		return new Date(iso).toLocaleDateString('es', { day: 'numeric', month: 'short' });
	}

	const grade = $derived.by(() => {
		const cg = data?.computed_grade;
		if (!cg) return null;
		return {
			tier: cg.level_code ?? '—',
			percent: Math.round(cg.normalized_value * 100),
			evaluatedPct:
				cg.total_weight > 0 ? Math.round((cg.evaluated_weight / cg.total_weight) * 100) : 0,
			min: cg.projected_min_normalized !== null ? Math.round(cg.projected_min_normalized * 100) : null,
			max: cg.projected_max_normalized !== null ? Math.round(cg.projected_max_normalized * 100) : null
		};
	});

	// The current attempt is the latest one — corrections supersede in order.
	function latestAttempt(ev: EvaluationDto): AttemptDto | null {
		const attempts = list(ev.attempts);
		if (attempts.length === 0) return null;
		return attempts.reduce((a, b) => (b.attempt_number >= a.attempt_number ? b : a));
	}

	async function handleScoreChange(ev: EvaluationDto, e: Event): Promise<void> {
		const target = e.currentTarget as HTMLInputElement;
		const parsed = Number(target.value);
		if (!Number.isFinite(parsed)) return;
		const clamped = Math.min(ev.max_score, Math.max(0, Math.round(parsed)));
		target.value = String(clamped);
		hapticTap();

		try {
			const attempt = latestAttempt(ev);
			if (attempt) {
				try {
					await correctScore(attempt.score_id, { raw_value: clamped });
				} catch (err) {
					// Someone corrected it first — refetch and retry on the new score id.
					if (err instanceof ApiError && err.code === 'already_superseded') {
						await reload();
						const fresh = data ? latestAttempt(evaluations.find((x) => x.assessment_id === ev.assessment_id) ?? ev) : null;
						if (fresh) await correctScore(fresh.score_id, { raw_value: clamped });
					} else {
						throw err;
					}
				}
			} else {
				await createScore(ev.assessment_id, { student_id: studentId, raw_value: clamped });
			}
			showToast('Nota guardada');
			void reload();
			reloadSoon();
		} catch {
			showToast('No se pudo guardar — revisa tu conexión');
		}
	}

	let showAddPracticeScore = $state(false);
	let deletingPracticeScoreId = $state<string | null>(null);

	async function handleAddPracticeScore(body: PracticeScoreCreateDto): Promise<void> {
		showAddPracticeScore = false;
		try {
			await createPracticeScore(classId, studentId, body);
			showToast('Nota personal guardada');
			void reload();
		} catch {
			showToast('No se pudo guardar la nota');
		}
	}

	async function handleDeletePracticeScore(id: string): Promise<void> {
		deletingPracticeScoreId = null;
		try {
			await deletePracticeScore(id);
			showToast('Nota personal eliminada');
			void reload();
		} catch {
			showToast('No se pudo eliminar la nota');
		}
	}

	let requestingSummary = $state(false);

	async function handleSummary(): Promise<void> {
		if (requestingSummary) return;
		requestingSummary = true;
		try {
			await requestSummary(classId, studentId);
			showToast('Generando resumen…');
			reloadSoon();
			setTimeout(() => {
				void reload();
				requestingSummary = false;
			}, 6000);
		} catch {
			requestingSummary = false;
			showToast('No se pudo generar el resumen');
		}
	}
</script>

<svelte:head>
	<title>{studentName}</title>
</svelte:head>

<TopBar back="/" />

<div class="body">
	{#if ready && data}
		<p class="title">{studentName}</p>
		<p class="subtitle">{courseName}</p>

		{#if grade}
			<div class="result">
				<p class="result-label">RESULTADO PARCIAL</p>
				<div class="result-head">
					<span class="tier">{grade.tier}</span>
					<span class="pct">{grade.percent}% de lo evaluado</span>
				</div>
				<div class="progress">
					<div class="progress-fill" style="width:{grade.evaluatedPct}%"></div>
				</div>
				<p class="result-foot">
					{grade.evaluatedPct}% del curso evaluado · falta {100 - grade.evaluatedPct}%
				</p>
			</div>

			{#if grade.min !== null && grade.max !== null}
				<div class="range">
					<p class="range-label">Rango posible al cierre</p>
					<div class="row">
						<span class="range-min">{grade.min}%</span>
						<div class="range-track"></div>
						<span class="range-max">{grade.max}%</span>
					</div>
					<p class="range-note">Según cómo rinda en lo que falta</p>
				</div>
			{/if}
		{/if}

		<p class="eyebrow">EVALUACIONES</p>

		<div class="stack">
			{#each evaluationModules as mod (mod.code)}
				{@const expanded = expandedModules.has(mod.code)}
				<div class="card module" class:expanded>
					<button
						class="module-header pressable"
						onclick={() => toggleModule(mod.code)}
						aria-expanded={expanded}
					>
						<div class="grow">
							<p class="component-name">{mod.label}</p>
							<p class="component-weight">
								Peso {Math.round(mod.weight * 100)}% · {scoredCount(mod)}/{mod.evaluations.length} evaluadas
							</p>
						</div>
						<span class="chevron" class:open={expanded}>
							<Icon name="chevron-right" size={16} />
						</span>
					</button>

					{#if expanded}
						<div class="module-body">
							{#each mod.evaluations as ev (ev.assessment_id)}
								{@const attempt = latestAttempt(ev)}
								{@const scored = attempt?.raw_value != null}
								<div class="row subgrade" class:unscored={!scored}>
									<p class="subgrade-name grow">{ev.title}</p>
									<span class="input-wrap">
										<input
											type="number"
											class="score-input"
											min="0"
											max={ev.max_score}
											value={attempt?.raw_value ?? ''}
											onchange={(e) => void handleScoreChange(ev, e)}
											aria-label={`Nota de ${ev.title}, sobre ${ev.max_score}`}
										/>
										<span class="max">/ {ev.max_score}</span>
									</span>
									<span class="score">
										{scored && attempt?.raw_value != null
											? `${Math.round((attempt.raw_value / ev.max_score) * 100)}%`
											: '—'}
									</span>
								</div>
							{/each}
						</div>
					{/if}
				</div>
			{/each}
		</div>

		{#if evaluationModules.length === 0}
			<p class="empty">Aún no hay evaluaciones para este curso.</p>
		{/if}

		<p class="eyebrow">NOTAS PERSONALES</p>

		<div class="stack">
			{#each practiceScores as ps (ps.id)}
				<div class="card row practice-score">
					<div class="grow">
						<p class="component-name">{ps.title}</p>
						<p class="component-weight">{kindLabels[ps.kind] ?? ps.kind} · {formatNoteDate(ps.recorded_at)}</p>
						{#if ps.note}
							<p class="practice-note">{ps.note}</p>
						{/if}
					</div>
					<span class="score">{ps.raw_value}/{ps.max_value}</span>
					<button
						class="action delete pressable"
						onclick={() => (deletingPracticeScoreId = ps.id)}
						aria-label="Eliminar nota personal"
						title="Eliminar"
					>
						<Icon name="trash" size={15} />
					</button>
				</div>
			{/each}
		</div>

		{#if practiceScores.length === 0}
			<p class="empty">Aún no hay notas personales.</p>
		{/if}

		<button
			class="btn-block pressable"
			onclick={() => (showAddPracticeScore = true)}
		>
			<Icon name="plus" size={16} />
			Añadir evaluación
		</button>

		<button class="btn-block ai pressable" disabled={requestingSummary} onclick={handleSummary}>
			<Icon name="sparkles" size={16} />
			{data.summary?.status === 'generating' || requestingSummary
				? 'Generando resumen…'
				: 'Generar resumen'}
		</button>

		{#if data.summary && (data.summary.status === 'ready' || data.summary.status === 'stale')}
			<AiSummaryCard
				title="Resumen de {data.summary.notes_count} notas de voz"
				bullets={data.summary.bullets}
			/>
		{/if}
	{:else if loadError}
		<p class="empty">
			No se pudieron cargar las notas.
			<button class="pill-light pressable" onclick={load}>Reintentar</button>
		</p>
	{/if}
</div>

{#if showAddPracticeScore}
	<AddPracticeScoreDialog
		onsubmit={handleAddPracticeScore}
		oncancel={() => (showAddPracticeScore = false)}
	/>
{/if}

{#if deletingPracticeScoreId}
	<ConfirmDialog
		title="¿Eliminar esta nota personal?"
		text="Esta acción no se puede deshacer."
		confirmLabel="Eliminar"
		onconfirm={() => void handleDeletePracticeScore(deletingPracticeScoreId!)}
		oncancel={() => (deletingPracticeScoreId = null)}
	/>
{/if}

<style>
	.title {
		margin: 0;
		font-weight: 500;
		font-size: 20px;
	}

	.subtitle {
		margin: 2px 0 var(--space-lg);
		font-size: 13px;
		color: var(--text-secondary);
	}

	.result {
		background: var(--text-primary);
		border-radius: var(--radius-lg);
		padding: var(--space-lg);
		margin-bottom: var(--space-lg);
	}

	.result-label {
		margin: 0 0 var(--space-sm);
		font-size: 10px;
		letter-spacing: 0.05em;
		color: var(--surface-1);
		font-family: var(--font-mono);
	}

	.result-head {
		display: flex;
		align-items: baseline;
		gap: 10px;
	}

	.tier {
		font-size: 26px;
		font-weight: 600;
		color: var(--surface-2);
	}

	.pct {
		font-size: 15px;
		color: var(--surface-1);
	}

	.progress {
		width: 100%;
		height: 6px;
		border-radius: var(--radius-sm);
		overflow: hidden;
		margin: 14px 0 var(--space-sm);
		background: rgba(255, 255, 255, 0.2);
	}

	.progress-fill {
		height: 100%;
		background: var(--surface-2);
	}

	.result-foot {
		margin: 0;
		font-size: 12px;
		color: var(--surface-1);
	}

	.range {
		background: var(--surface-1);
		border-radius: var(--radius);
		padding: var(--space-md) 14px;
		margin-bottom: 20px;
	}

	.range-label {
		margin: 0 0 6px;
		font-size: 11px;
		color: var(--text-secondary);
	}

	.range .row {
		gap: var(--space-sm);
	}

	.range-min,
	.range-max {
		font-size: 15px;
		font-weight: 500;
	}

	.range-min {
		color: var(--text-danger);
	}

	.range-max {
		color: var(--text-success);
	}

	.range-track {
		flex: 1;
		height: 4px;
		border-radius: 2px;
		background: linear-gradient(to right, var(--border-strong), var(--fill-accent));
	}

	.range-note {
		margin: 6px 0 0;
		font-size: 11px;
		color: var(--text-muted);
	}

	.stack {
		display: flex;
		flex-direction: column;
		gap: var(--space-sm);
		margin-bottom: 20px;
	}

	.grow {
		flex: 1;
		min-width: 0;
	}

	.component-name {
		margin: 0;
		font-size: 14px;
	}

	.component-weight {
		margin: 0;
		font-size: 11px;
		color: var(--text-muted);
	}

	.module {
		padding: 0;
		overflow: hidden;
	}

	.module-header {
		display: flex;
		align-items: center;
		gap: 10px;
		width: 100%;
		padding: var(--space-md) 14px;
		background: transparent;
		border: none;
		text-align: left;
		color: inherit;
		font: inherit;
		cursor: pointer;
	}

	.chevron {
		display: inline-flex;
		flex-shrink: 0;
		color: var(--text-muted);
		transition: transform 150ms;
	}

	.chevron.open {
		transform: rotate(90deg);
	}

	.module-body {
		display: flex;
		flex-direction: column;
		gap: var(--space-sm);
		padding: var(--space-sm) 14px var(--space-md);
		border-top: 0.5px solid var(--border);
	}

	.subgrade {
		gap: 10px;
	}

	.subgrade-name {
		margin: 0;
		font-size: 13px;
		color: var(--text-secondary);
	}

	.subgrade.unscored .subgrade-name {
		color: var(--text-muted);
	}

	.input-wrap {
		display: flex;
		align-items: center;
		gap: var(--space-xs);
	}

	.score-input {
		width: 52px;
		font-size: 13px;
		font-weight: 500;
		color: var(--text-primary);
		background: var(--surface-1);
		border: 0.5px solid var(--border);
		border-radius: var(--radius-sm);
		padding: var(--space-xs) 6px;
		text-align: right;
	}

	.score-input:focus {
		outline: none;
		border-color: var(--border-strong);
	}

	.max {
		font-size: 13px;
		color: var(--text-secondary);
	}

	.score {
		font-size: 13px;
		font-weight: 500;
		min-width: 40px;
		text-align: right;
	}

	.practice-score {
		align-items: flex-start;
	}

	.practice-note {
		margin: 4px 0 0;
		font-size: 12px;
		color: var(--text-secondary);
	}

	.action {
		position: relative;
		display: inline-flex;
		align-items: center;
		justify-content: center;
		color: var(--text-muted);
	}

	.action.delete {
		color: var(--text-danger);
	}

	/* Assistant action — carries the accent. */
	.ai {
		background: var(--fill-accent);
		color: var(--on-accent);
		margin-bottom: var(--space-sm);
	}

	.empty {
		font-size: 14px;
		color: var(--text-secondary);
	}
</style>
