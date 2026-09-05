<script lang="ts">
	import { onMount } from 'svelte';
	import { page } from '$app/state';
	import { ApiError, list } from '$lib/api/client';
	import type {
		AttemptDto,
		CompetencyCriteriaDto,
		CriterionDto,
		EvaluationDto,
		GradingComponentDto,
		PracticeScoreCreateDto,
		StudentGradesDto,
	} from '$lib/api/dto';
	import {
		assertCompetencyLevel,
		getStudentCompetencies,
		upsertConclusion,
	} from '$lib/api/endpoints/competencies';
	import { deleteAssessment, getGradingComponents } from '$lib/api/endpoints/classes';
	import { getClassCriteria } from '$lib/api/endpoints/criteria';
	import {
		correctScore,
		createPracticeScore,
		createScore,
		deletePracticeScore,
		getStudentGrades,
	} from '$lib/api/endpoints/grades';
	import { toCompetencyLevel } from '$lib/api/mappers';
	import AddPracticeScoreDialog from '$lib/components/AddPracticeScoreDialog.svelte';
	import CompetencyCard from '$lib/components/CompetencyCard.svelte';
	import ConfirmDialog from '$lib/components/ConfirmDialog.svelte';
	import LevelBadge from '$lib/components/LevelBadge.svelte';
	import Icon from '$lib/components/Icon.svelte';
	import TopBar from '$lib/components/TopBar.svelte';
	import type { Tier } from '$lib/grades';
	import { hapticTap } from '$lib/haptics';
	import { usesInternalGrading } from '$lib/stores';
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
	let criteriaGroups = $state<CompetencyCriteriaDto[]>([]);
	let gradingComponents = $state<GradingComponentDto[]>([]);
	// The competency cards read the criterios by competency id; the evidence
	// dialog needs them grouped, so the grouped list is what is held and the
	// map is derived from it.
	const criteriaByCompetency = $derived(indexCriteria(criteriaGroups));

	async function load(): Promise<void> {
		ready = false;
		loadError = false;
		try {
			const [grades, comps, crits, components] = await Promise.all([
				getStudentGrades(classId, studentId),
				getStudentCompetencies(classId, studentId),
				getClassCriteria(classId),
				getGradingComponents(classId),
			]);
			data = grades;
			competencies = list(comps.competencies).map(toCompetencyLevel);
			criteriaGroups = list(crits.competencies);
			gradingComponents = list(components.components);
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

	function indexCriteria(rows: CompetencyCriteriaDto[]): Map<string, CriterionDto[]> {
		const out = new Map<string, CriterionDto[]>();
		for (const row of rows) out.set(row.competency_id, list(row.criteria));
		return out;
	}

	async function reloadCompetencies(): Promise<void> {
		try {
			const [comps, crits] = await Promise.all([
				getStudentCompetencies(classId, studentId),
				getClassCriteria(classId),
			]);
			competencies = list(comps.competencies).map(toCompetencyLevel);
			criteriaGroups = list(crits.competencies);
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
					evaluations: [],
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
		otro: 'Otro',
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
				cg.total_weight > 0 ? Math.round((cg.evaluated_weight / cg.total_weight) * 100) : 0,
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
		// A piece with no denominator has nothing to clamp against, and no mark
		// input is rendered for one — this is belt and braces.
		if (ev.max_score === null) return;
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
						const fresh = data
							? latestAttempt(evaluations.find((x) => x.assessment_id === ev.assessment_id) ?? ev)
							: null;
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
				status,
			});
			showToast(status === 'final' ? 'Conclusión guardada' : 'Borrador guardado');
			await reloadCompetencies();
		} catch (err) {
			showToast(err instanceof ApiError ? err.message : 'No se pudo guardar — revisa tu conexión');
		}
	}

	let deletingEvidence = $state<EvaluationDto | null>(null);

	// Evidence created from this screen belongs to this student alone, so the
	// form is opened with the student in the query. Class work is filed from the
	// área, which speaks for the class rather than for one student.
	const addEvidenceHref = $derived(
		`/class/${classId}/evidence/new?student=${studentId}&name=${encodeURIComponent(studentName)}&course=${encodeURIComponent(courseName)}`
	);

	async function handleDeleteEvidence(ev: EvaluationDto): Promise<void> {
		deletingEvidence = null;
		try {
			await deleteAssessment(ev.assessment_id);
			showToast('Evidencia eliminada');
			await reload();
			reloadSoon();
		} catch (err) {
			showToast(err instanceof ApiError ? err.message : 'No se pudo eliminar la evidencia');
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
						onLevelChange={handleLevelChange}
						onSaveConclusion={handleSaveConclusion}
					/>
				{/each}
			</div>
		{/if}

		<p class="eyebrow">EVIDENCIA</p>
		<p class="evidence-note">
			{#if $usesInternalGrading}
				Cada evidencia se registra una vez y se lee dos veces: la nota alimenta el sistema interno
				del colegio, el nivel por criterio alimenta el registro oficial. Las notas no determinan el
				nivel de logro ni se promedian para obtenerlo.
			{:else}
				Valora cada evidencia contra los criterios que declara. El nivel de logro de la competencia
				sigue siendo tu juicio sobre todo el periodo.
			{/if}
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
								{@const numeric = ev.value_scale === 'numeric' && ev.max_score !== null}
								{@const scored = attempt?.raw_value != null || attempt?.level != null}
								{@const crits = list(ev.criteria)}
								<div class="subgrade" class:unscored={!scored && numeric && $usesInternalGrading}>
									<div class="row">
										<p class="subgrade-name grow">{ev.title}</p>
										{#if numeric && $usesInternalGrading}
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
										{:else if ev.value_scale === 'ordinal'}
											<!-- Read-only here. This screen is the inventory of everything filed;
											     valuing a piece of work happens on the evaluating screen, beside
											     the criterios it was read against. -->
											{#if attempt?.level != null}
												<LevelBadge tier={attempt.level} size={24} />
											{:else}
												<span class="unvalued">Sin valorar</span>
											{/if}
										{/if}
										<button
											class="action delete pressable"
											onclick={() => (deletingEvidence = ev)}
											aria-label={`Eliminar ${ev.title}`}
											title="Eliminar"
										>
											<Icon name="trash" size={15} />
										</button>
									</div>
									<p class="tags">
										<span class="kind">{kindLabels[ev.kind] ?? ev.kind}</span>
										{#if ev.is_personal}
											<span class="personal">Solo este alumno</span>
										{/if}
										{#if $usesInternalGrading && !ev.counts_toward_internal}
											<span class="excluded">Fuera del promedio interno</span>
										{/if}
									</p>

									<!-- Read-only. A criterio says what to look at in this piece of
									     work; it is not itself graded. The judgement that gets recorded
									     is the nivel de logro of the competencia, on the student's
									     screen. -->
									{#if crits.length > 0}
										<p class="evidences">
											{crits.map((c) => c.code ?? 'CRIT').join(' ')} · {crits
												.map((c) => c.description)
												.join(' ')}
										</p>
									{:else}
										<p class="evidences">Sin criterios declarados: no dice contra qué leerla.</p>
									{/if}
								</div>
							{/each}
						</div>
					{/if}
				</div>
			{/each}
		</div>

		{#if evaluationModules.length === 0}
			<p class="empty">Aún no hay evidencias para este curso.</p>
		{/if}

		<a class="btn-block add-evidence pressable" href={addEvidenceHref} onclick={hapticTap}>
			<Icon name="plus" size={16} />
			Añadir evidencia
		</a>

		{#if internalGrade && $usesInternalGrading}
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
							Promedio ponderado propio del colegio. No es el registro oficial: el MINEDU evalúa por
							competencias y el nivel de logro lo asignas tú.
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
						<p class="component-weight">
							{kindLabels[ps.kind] ?? ps.kind} · {formatNoteDate(ps.recorded_at)}
						</p>
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

		<button class="btn-block pressable" onclick={() => (showAddPracticeScore = true)}>
			<Icon name="plus" size={16} />
			Añadir nota personal
		</button>
	{:else if loadError}
		<p class="empty">
			No se pudieron cargar las notas.
			<button class="pill-light pressable" onclick={load}>Reintentar</button>
		</p>
	{/if}
</div>

{#if deletingEvidence}
	<ConfirmDialog
		title="¿Eliminar «{deletingEvidence.title}»?"
		text="Las notas ya registradas quedan en el historial, pero dejan de verse aquí y de contar en el sistema interno."
		confirmLabel="Eliminar"
		onconfirm={() => void handleDeleteEvidence(deletingEvidence!)}
		oncancel={() => (deletingEvidence = null)}
	/>
{/if}

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

	/* An ordinal piece nobody has valued yet. Not a zero, and not a C. */
	.unvalued {
		flex-shrink: 0;
		font-size: 12px;
		color: var(--text-muted);
	}

	.excluded {
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

	/* The kind (quiz, tarea, proyecto...) rides as a label on the row: the
	   accordion groups by grading component, not by kind, so the row is where
	   the kind has to be legible. */
	.tags {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-xs);
		margin: 4px 0 0;
		font-size: 11px;
	}

	.kind,
	.personal {
		border-radius: var(--radius-sm);
		padding: 1px 6px;
		background: var(--surface-1);
		color: var(--text-muted);
	}

	.personal {
		color: var(--text-secondary);
		border: 0.5px solid var(--border);
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

	/* Closes the EVIDENCIA section, so it needs the same gap the eyebrows use
	   before NOTAS PERSONALES starts. */
	.add-evidence {
		margin-bottom: var(--space-lg);
	}

	.empty {
		font-size: 14px;
		color: var(--text-secondary);
	}
</style>
