<script lang="ts">
	import { onMount } from 'svelte';
	import { page } from '$app/state';
	import { ApiError, list } from '$lib/api/client';
	import type {
		AttemptDto,
		CompetencyCriteriaDto,
		CriterionDto,
		EvaluationDto,
		PracticeScoreCreateDto,
		StudentGradesDto
	} from '$lib/api/dto';
	import {
		assertCompetencyLevel,
		getStudentCompetencies,
		upsertConclusion
	} from '$lib/api/endpoints/competencies';
	import { assertCriterionLevel, getClassCriteria } from '$lib/api/endpoints/criteria';
	import {
		correctScore,
		createPracticeScore,
		createScore,
		deletePracticeScore,
		getStudentGrades,
		requestSummary
	} from '$lib/api/endpoints/grades';
	import { toCompetencyLevel } from '$lib/api/mappers';
	import AddPracticeScoreDialog from '$lib/components/AddPracticeScoreDialog.svelte';
	import AiSummaryCard from '$lib/components/AiSummaryCard.svelte';
	import CompetencyCard from '$lib/components/CompetencyCard.svelte';
	import ConfirmDialog from '$lib/components/ConfirmDialog.svelte';
	import Icon from '$lib/components/Icon.svelte';
	import TopBar from '$lib/components/TopBar.svelte';
	import type { Tier } from '$lib/grades';
	import { hapticTap } from '$lib/haptics';
	import { showToast } from '$lib/toast';
	import type { CompetencyLevel } from '$lib/types';

	const studentId = $derived(page.params.studentId ?? '');
	// Class id and display names travel as query params — the grades endpoint
	// doesn't return them, and the SPA has no other student lookup.
	const classId = $derived(page.url.searchParams.get('class') ?? '');
	const studentName = $derived(page.url.searchParams.get('name') ?? 'Alumno');
	const courseName = $derived(page.url.searchParams.get('course') ?? '');

	let ready = $state(false);
	let loadError = $state(false);
	let data = $state<StudentGradesDto | null>(null);
	let competencies = $state<CompetencyLevel[]>([]);
	let criteriaByCompetency = $state<Map<string, CriterionDto[]>>(new Map());

	async function load(): Promise<void> {
		ready = false;
		loadError = false;
		try {
			const [grades, comps, crits] = await Promise.all([
				getStudentGrades(classId, studentId),
				getStudentCompetencies(classId, studentId),
				getClassCriteria(classId, studentId)
			]);
			data = grades;
			competencies = list(comps.competencies).map(toCompetencyLevel);
			criteriaByCompetency = indexCriteria(crits.competencies);
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

	function indexCriteria(rows: CompetencyCriteriaDto[] | null): Map<string, CriterionDto[]> {
		const out = new Map<string, CriterionDto[]>();
		for (const row of list(rows)) out.set(row.competency_id, list(row.criteria));
		return out;
	}

	async function reloadCompetencies(): Promise<void> {
		try {
			const [comps, crits] = await Promise.all([
				getStudentCompetencies(classId, studentId),
				getClassCriteria(classId, studentId)
			]);
			competencies = list(comps.competencies).map(toCompetencyLevel);
			criteriaByCompetency = indexCriteria(crits.competencies);
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
		evaluations: EvaluationDto[];
	};

	// Groups the flat evaluation list into one accordion section per grading
	// component, in the order each first appears. Deliberately carries no
	// weight: these are pieces of evidence, not shares of a final grade.
	const evaluationModules = $derived.by((): EvaluationModule[] => {
		const byCode = new Map<string, EvaluationModule>();
		for (const ev of evaluations) {
			let mod = byCode.get(ev.component_code);
			if (!mod) {
				// The server sends the component's display name (gc.name); the code
				// stays the grouping key. Fallback covers a stale API binary only.
				mod = {
					code: ev.component_code,
					label: ev.component_name || ev.component_code,
					evaluations: []
				};
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

	// The school's own internal weighted system. Shown collapsed at the foot of
	// the screen and labelled as such — it is not the official record and
	// carries no projection.
	const internalGrade = $derived.by(() => {
		const cg = data?.computed_grade;
		if (!cg) return null;
		return {
			display: cg.display_value ?? String(Math.round(cg.normalized_value * 100)),
			evaluatedPct:
				cg.total_weight > 0 ? Math.round((cg.evaluated_weight / cg.total_weight) * 100) : 0
		};
	});

	let showInternal = $state(false);

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

	async function handleLevelChange(competencyId: string, level: Tier): Promise<void> {
		hapticTap();
		try {
			await assertCompetencyLevel(classId, studentId, { competency_id: competencyId, level });
			showToast('Nivel guardado');
			await reloadCompetencies();
		} catch (err) {
			showToast(err instanceof ApiError ? err.message : 'No se pudo guardar — revisa tu conexión');
		}
	}

	async function handleCriterionLevelChange(criterionId: string, level: Tier): Promise<void> {
		hapticTap();
		try {
			await assertCriterionLevel(classId, studentId, { criterion_id: criterionId, level });
			showToast('Criterio guardado');
			await reloadCompetencies();
		} catch (err) {
			showToast(err instanceof ApiError ? err.message : 'No se pudo guardar — revisa tu conexión');
		}
	}

	async function handleSaveConclusion(
		competencyId: string,
		body: string,
		includesRecommendations: boolean,
		status: 'draft' | 'final'
	): Promise<void> {
		try {
			await upsertConclusion(classId, studentId, {
				competency_id: competencyId,
				body,
				includes_recommendations: includesRecommendations,
				status
			});
			showToast(status === 'final' ? 'Conclusión guardada' : 'Borrador guardado');
			await reloadCompetencies();
		} catch (err) {
			showToast(err instanceof ApiError ? err.message : 'No se pudo guardar — revisa tu conexión');
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

<!-- Reached from both the class roster and the lesson screen, so the back arrow
     returns to whichever it was. The class page is the fallback for a deep link
     or a refresh, where there is no in-app history to pop. -->
<TopBar back={classId ? `/class/${classId}` : '/'} useHistory />

<div class="body">
	{#if ready && data}
		<p class="title">{studentName}</p>
		<p class="subtitle">{courseName}</p>

		{#if competencies.length > 0}
			<p class="eyebrow">NIVELES DE LOGRO POR COMPETENCIA</p>
			<div class="stack">
				{#each competencies as comp (comp.competencyId)}
					<CompetencyCard
						competency={comp}
						criteria={criteriaByCompetency.get(comp.competencyId) ?? []}
						onCriterionLevelChange={handleCriterionLevelChange}
						onLevelChange={handleLevelChange}
						onSaveConclusion={handleSaveConclusion}
					/>
				{/each}
			</div>
		{/if}

		<p class="eyebrow">EVIDENCIA</p>
		<p class="evidence-note">
			Las notas son evidencia para tu juicio docente. No determinan el nivel de
			logro ni se promedian para obtenerlo.
		</p>

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
								{scoredCount(mod)}/{mod.evaluations.length} evaluadas
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
								<div class="subgrade" class:unscored={!scored}>
									<div class="row">
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
									</div>
									{#if list(ev.criteria).length > 0}
										<p class="evidences">
											Evidencia: {list(ev.criteria)
												.map((c) => c.code ?? c.description)
												.join(' · ')}
										</p>
									{/if}
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

		{#if internalGrade}
			<div class="card internal">
				<button
					type="button"
					class="internal-header pressable"
					onclick={() => (showInternal = !showInternal)}
					aria-expanded={showInternal}
				>
					<p class="grow internal-title">Sistema interno de la IE</p>
					<span class="chevron" class:open={showInternal}>
						<Icon name="chevron-right" size={16} />
					</span>
				</button>
				{#if showInternal}
					<div class="internal-body">
						<p class="internal-value">{internalGrade.display}</p>
						<p class="internal-foot">{internalGrade.evaluatedPct}% del curso evaluado</p>
						<p class="internal-note">
							Promedio ponderado propio del colegio. No es el registro oficial: el
							MINEDU evalúa por competencias y el nivel de logro lo asignas tú.
						</p>
					</div>
				{/if}
			</div>
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

	.evidence-note {
		margin: 0 0 var(--space-sm);
		font-size: 11px;
		line-height: 1.4;
		color: var(--text-muted);
	}

	.evidences {
		margin: 4px 0 0;
		font-size: 11px;
		line-height: 1.35;
		color: var(--text-muted);
	}

	.internal {
		padding: 0;
		margin-top: var(--space-lg);
	}

	.internal-header {
		display: flex;
		align-items: center;
		gap: var(--space-sm);
		width: 100%;
		padding: var(--space-md);
		background: none;
		border: none;
		font-family: inherit;
		text-align: left;
		cursor: pointer;
	}

	.internal-title {
		margin: 0;
		font-size: 13px;
		color: var(--text-secondary);
	}

	.internal-body {
		padding: 0 var(--space-md) var(--space-md);
	}

	.internal-value {
		margin: 0;
		font-size: 22px;
		font-weight: 600;
	}

	.internal-foot {
		margin: 2px 0 0;
		font-size: 12px;
		color: var(--text-secondary);
	}

	.internal-note {
		margin: var(--space-sm) 0 0;
		font-size: 11px;
		line-height: 1.4;
		color: var(--text-muted);
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
