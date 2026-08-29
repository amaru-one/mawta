<script lang="ts">
	// Files one piece of *evidencia* — a quiz, a project, an oral defence.
	//
	// Two callers, one dialog. The student's grades screen passes `scope:
	// 'student'`, so what it creates belongs to that student alone; the SIAGIE
	// report passes `scope: 'class'` and creates a column for the whole class.
	// The scope is fixed by the caller and shown as a caption rather than
	// offered as a control: which screen you are on is already the answer, and
	// a picker here would only invite filing class work from a student's page.
	import { untrack } from 'svelte';
	import { scale } from 'svelte/transition';
	import type {
		AssessmentCreateDto,
		AssessmentKind,
		CompetencyCriteriaDto,
		GradingComponentDto
	} from '$lib/api/dto';
	import { list } from '$lib/api/client';

	interface Props {
		components: GradingComponentDto[];
		competencies: CompetencyCriteriaDto[];
		scope: 'student' | 'class';
		studentName?: string;
		/** Whether the school runs its own weighted numeric system. False hides
		 *  the "cuenta para el promedio interno" control entirely — there is no
		 *  average for the evidence to count towards. */
		usesInternalGrading?: boolean;
		onsubmit: (data: AssessmentCreateDto) => void;
		oncancel: () => void;
	}

	let {
		components,
		competencies,
		scope,
		studentName,
		usesInternalGrading = true,
		onsubmit,
		oncancel
	}: Props = $props();

	const kindOptions: { value: AssessmentKind; label: string }[] = [
		{ value: 'quiz', label: 'Quiz' },
		{ value: 'examen', label: 'Examen' },
		{ value: 'practica', label: 'Práctica' },
		{ value: 'tarea', label: 'Tarea' },
		{ value: 'proyecto', label: 'Proyecto' },
		{ value: 'exposicion', label: 'Exposición' },
		{ value: 'participacion', label: 'Participación' },
		{ value: 'rubrica', label: 'Rúbrica' },
		{ value: 'otro', label: 'Otro' }
	];

	let title = $state('');
	let kind = $state<AssessmentKind>('quiz');
	// Empty means "not touched yet", which resolves to the first component —
	// reading components[0] into state at init would only capture its value
	// once, and the list is a prop.
	let componentCode = $state('');
	let maxScore = $state('20');
	let dueAt = $state('');
	let selectedCriteria = $state<Set<string>>(new Set());
	// Class work counts towards the school's average; a per-student piece does
	// not, by default. Both stay the teacher's call — this only picks the
	// sensible starting point. A recovery task that lifted one student's average
	// would hand them an opportunity nobody else got, and that is the common
	// reason to file evidence for a single student.
	//
	// `untrack` because capturing the initial value is the point: `scope` is
	// fixed by the caller for the life of the dialog, and re-deriving would
	// undo a teacher's own choice mid-form. Same idiom as CompetencyCard's
	// conclusion draft.
	let countsTowardInternal = $state(untrack(() => scope === 'class'));

	const titleId = `add-evidence-${Math.random().toString(36).slice(2, 8)}`;

	const effectiveComponent = $derived(componentCode || (components[0]?.code ?? ''));

	const canSubmit = $derived(
		title.trim() !== '' && effectiveComponent !== '' && Number(maxScore) > 0
	);

	function toggleCriterion(id: string): void {
		const next = new Set(selectedCriteria);
		if (next.has(id)) {
			next.delete(id);
		} else {
			next.add(id);
		}
		selectedCriteria = next;
	}

	function handleSubmit(e: Event): void {
		e.preventDefault();
		if (!canSubmit) return;
		onsubmit({
			title: title.trim(),
			kind,
			component_code: effectiveComponent,
			// Still sent when the school has no internal system: assessments.max_score
			// is not nullable, and the default denominator is harmless when no mark
			// will ever be typed against it.
			max_score: Number(maxScore),
			// The input is a plain date; the API takes a timestamp.
			due_at: dueAt === '' ? null : `${dueAt}T23:59:00-05:00`,
			counts_toward_internal: usesInternalGrading && countsTowardInternal,
			criterion_ids: [...selectedCriteria]
		});
	}
</script>

<svelte:window onkeydown={(e) => e.key === 'Escape' && oncancel()} />

<div
	class="dialog"
	in:scale={{ start: 0.95, duration: 150 }}
	out:scale={{ start: 0.95, duration: 150 }}
	role="dialog"
	aria-modal="true"
	aria-labelledby={titleId}
>
	<button class="backdrop" onclick={oncancel} aria-label="Cerrar diálogo" tabindex="-1"></button>
	<form class="content" onsubmit={handleSubmit}>
		<p class="title" id={titleId}>Añadir evidencia</p>
		<p class="hint">
			{#if scope === 'student'}
				Solo para {studentName ?? 'este alumno'}. No aparece en la lista de los demás.
			{:else}
				Para toda la clase. Aparece en la pantalla de cada alumno, sin nota.
			{/if}
		</p>

		<label class="field">
			<span>Título</span>
			<input type="text" bind:value={title} placeholder="Exposición del proyecto" required />
		</label>

		<label class="field">
			<span>Tipo</span>
			<select bind:value={kind}>
				{#each kindOptions as opt (opt.value)}
					<option value={opt.value}>{opt.label}</option>
				{/each}
			</select>
		</label>

		<label class="field">
			<span>Componente</span>
			{#if components.length > 0}
				<select
					value={effectiveComponent}
					onchange={(e) => (componentCode = e.currentTarget.value)}
				>
					{#each components as c (c.code)}
						<option value={c.code}>{c.name}</option>
					{/each}
				</select>
			{:else}
				<p class="warn">Esta clase no tiene componentes de calificación configurados.</p>
			{/if}
		</label>

		<div class="row-fields">
			{#if usesInternalGrading}
				<label class="field score">
					<span>Sobre</span>
					<input type="number" bind:value={maxScore} step="0.01" min="0.01" required />
				</label>
			{/if}
			<label class="field score">
				<span>Entrega (opcional)</span>
				<input type="date" bind:value={dueAt} />
			</label>
		</div>

		{#if usesInternalGrading}
			<label class="internal">
				<input type="checkbox" bind:checked={countsTowardInternal} />
				<span class="grow">
					Cuenta para el promedio interno del colegio
					<span class="internal-note">
						El nivel por criterio se registra igual: el registro oficial no
						depende de esta casilla.
					</span>
				</span>
			</label>
		{/if}

		{#if competencies.length > 0}
			<div class="field">
				<span>¿Qué criterios evidencia? (opcional)</span>
				<div class="criteria">
					{#each competencies as comp (comp.competency_id)}
						{@const crits = list(comp.criteria)}
						{#if crits.length > 0}
							<p class="comp-name">{comp.name}</p>
							{#each crits as c (c.criterion_id)}
								<label class="criterion">
									<input
										type="checkbox"
										checked={selectedCriteria.has(c.criterion_id)}
										onchange={() => toggleCriterion(c.criterion_id)}
									/>
									<span class="grow">{c.code ? `${c.code} · ` : ''}{c.description}</span>
								</label>
							{/each}
						{/if}
					{/each}
				</div>
			</div>
		{/if}

		<div class="actions">
			<button type="button" class="cancel pressable" onclick={oncancel}>Cancelar</button>
			<button type="submit" class="confirm pressable" disabled={!canSubmit}>Guardar</button>
		</div>
	</form>
</div>

<style>
	.dialog {
		position: fixed;
		inset: 0;
		display: flex;
		align-items: center;
		justify-content: center;
		z-index: 2000;
		padding: var(--space-lg);
	}

	.backdrop {
		position: absolute;
		inset: 0;
		background: rgba(20, 20, 20, 0.5);
		border: none;
		cursor: pointer;
	}

	.content {
		position: relative;
		display: flex;
		flex-direction: column;
		gap: var(--space-md);
		background: var(--surface-2);
		border-radius: var(--radius-lg);
		padding: var(--space-xl);
		width: 100%;
		max-width: 360px;
		max-height: 85vh;
		overflow-y: auto;
		box-shadow: var(--shadow-lg);
	}

	.title {
		margin: 0;
		font-size: 16px;
		font-weight: 500;
	}

	.hint {
		margin: -6px 0 0;
		font-size: 12px;
		color: var(--text-secondary);
	}

	.field {
		display: flex;
		flex-direction: column;
		gap: 6px;
		font-size: 12px;
		color: var(--text-secondary);
	}

	.field input,
	.field select {
		font-size: 14px;
		color: var(--text-primary);
		background: var(--surface-1);
		border: 0.5px solid var(--border);
		border-radius: var(--radius-sm);
		padding: var(--space-sm) 10px;
		font-family: inherit;
	}

	.field input:focus,
	.field select:focus {
		outline: none;
		border-color: var(--border-strong);
	}

	.warn {
		margin: 0;
		font-size: 12px;
		color: var(--text-muted);
	}

	.row-fields {
		display: flex;
		align-items: flex-end;
		gap: var(--space-sm);
	}

	.score {
		flex: 1;
		min-width: 0;
	}

	.internal {
		display: flex;
		align-items: flex-start;
		gap: var(--space-sm);
		font-size: 13px;
		color: var(--text-primary);
		line-height: 1.35;
	}

	.internal input {
		flex-shrink: 0;
		margin-top: 2px;
	}

	.internal-note {
		display: block;
		margin-top: 2px;
		font-size: 11px;
		color: var(--text-muted);
	}

	.criteria {
		display: flex;
		flex-direction: column;
		gap: var(--space-sm);
		max-height: 180px;
		overflow-y: auto;
		background: var(--surface-1);
		border: 0.5px solid var(--border);
		border-radius: var(--radius-sm);
		padding: var(--space-sm) 10px;
	}

	.comp-name {
		margin: var(--space-sm) 0 0;
		font-size: 11px;
		font-weight: 500;
		color: var(--text-muted);
	}

	.comp-name:first-child {
		margin-top: 0;
	}

	/* Long criterio texts wrap freely beside the fixed-width checkbox — the
	   app's standard overflow idiom, no ellipsis. */
	.criterion {
		display: flex;
		align-items: flex-start;
		gap: var(--space-sm);
		font-size: 13px;
		color: var(--text-primary);
		line-height: 1.35;
	}

	.criterion input {
		flex-shrink: 0;
		margin-top: 2px;
	}

	.grow {
		flex: 1;
		min-width: 0;
	}

	.actions {
		display: flex;
		gap: var(--space-md);
		justify-content: flex-end;
		margin-top: var(--space-sm);
	}

	.cancel,
	.confirm {
		padding: 10px var(--space-lg);
		min-height: 36px;
		border-radius: var(--radius-md);
		font-size: 14px;
		font-weight: 500;
	}

	.cancel {
		background: var(--surface-1);
		color: var(--text-primary);
	}

	.confirm {
		background: var(--fill-accent);
		color: var(--on-accent);
	}

	.confirm:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}
</style>
