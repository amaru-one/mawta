<script lang="ts">
	// The criteria step of a saved experience. One competencia at a time, with
	// ‹ › between them: its capacidades say in words which ones a criterio
	// already looks at, and the criterios are the protagonists. A criterio is a
	// grade desempeño landed on the situation; it can look at several
	// capacidades of its competencia and is listed once. Mawta only fills gaps
	// when asked, and "Continuar" waits until every competencia was seen.
	import { onMount } from 'svelte';
	import { page } from '$app/state';
	import { goto } from '$app/navigation';
	import { ApiError, list } from '$lib/api/client';
	import type {
		CurriculumCompetencyDto,
		CurriculumDto,
		ExperienceCriterionDto,
		ExperienceDto,
		GenerationDto,
	} from '$lib/api/dto';
	import {
		acceptCriterion,
		createCriterion,
		deleteCriterion,
		generateCriteria,
		getClassCurriculum,
		getExperience,
		getGeneration,
		updateCriterion,
	} from '$lib/api/endpoints/planning';
	import ConfirmDialog from '$lib/components/ConfirmDialog.svelte';
	import Icon from '$lib/components/Icon.svelte';
	import TopBar from '$lib/components/TopBar.svelte';
	import { hapticTap } from '$lib/haptics';
	import { showToast } from '$lib/toast';

	const courseId = $derived(page.params.courseId ?? '');
	const experienceId = $derived(page.params.experienceId ?? '');

	let ready = $state(false);
	let loadError = $state(false);
	let experience = $state<ExperienceDto | null>(null);
	let curriculum = $state<CurriculumDto | null>(null);

	async function load(): Promise<void> {
		ready = false;
		loadError = false;
		try {
			[experience, curriculum] = await Promise.all([
				getExperience(experienceId),
				getClassCurriculum(courseId),
			]);
			ready = true;
		} catch {
			loadError = true;
		}
	}

	// After a write only the experience changes; the curriculum is fixed data.
	async function reload(): Promise<void> {
		try {
			experience = await getExperience(experienceId);
		} catch {
			showToast('No se pudo actualizar la experiencia');
		}
	}

	onMount(load);

	// ---- one competencia at a time ----

	let compIdx = $state(0);
	let visited = $state<string[]>([]);

	const comps = $derived(list(experience?.competencies));
	const current = $derived(comps[compIdx] ?? null);
	const currentCurriculum = $derived<CurriculumCompetencyDto | null>(
		list(curriculum?.competencies).find((c) => c.id === current?.id) ?? null
	);
	const capabilities = $derived(list(currentCurriculum?.capabilities));
	const performances = $derived(list(currentCurriculum?.performances));
	const criteria = $derived(
		list(experience?.criteria).filter((criterion) => criterion.competency_id === current?.id)
	);
	const covered = $derived(
		new Set(criteria.flatMap((criterion) => list(criterion.capability_ids)))
	);
	const missing = $derived(capabilities.filter((capability) => !covered.has(capability.id)));
	const pending = $derived(criteria.some(isProposal));
	const unseen = $derived(comps.filter((c) => !visited.includes(c.id)).length);

	// Seeing a competencia is what "Continuar" waits for.
	$effect(() => {
		const id = current?.id;
		if (id && !visited.includes(id)) visited = [...visited, id];
	});

	function go(step: number): void {
		const next = compIdx + step;
		if (next < 0 || next >= comps.length) return;
		hapticTap();
		form = null;
		compIdx = next;
	}

	function isProposal(criterion: ExperienceCriterionDto): boolean {
		return criterion.proposed_by === 'mawta' && criterion.accepted_at === null;
	}

	function capabilityName(id: string): string {
		return capabilities.find((capability) => capability.id === id)?.name ?? '';
	}

	function performanceText(id: string): string {
		return performances.find((performance) => performance.id === id)?.text ?? '';
	}

	// "a", "a y b", "a, b y c"
	function joinY(items: string[]): string {
		if (items.length <= 1) return items.join('');
		return `${items.slice(0, -1).join(', ')} y ${items[items.length - 1]}`;
	}

	function shortText(text: string, max = 90): string {
		if (text.length <= max) return text;
		return `${text.slice(0, max).replace(/\s+\S*$/, '')}…`;
	}

	// ---- create and edit ----

	type CriterionForm = {
		id: string | null;
		performanceId: string;
		capabilityIds: string[];
		description: string;
	};

	let form = $state<CriterionForm | null>(null);
	let saving = $state(false);
	let formError = $state<string | null>(null);

	// The contract's codes, in the screen's own words.
	const ERROR_TEXT: Record<string, string> = {
		capability_not_in_competency: 'Una de las capacidades no es de esta competencia.',
		criterion_needs_capability: 'Elige al menos una capacidad que mire el criterio.',
		performance_not_in_grade: 'Ese desempeño no es de esta competencia para el grado de la clase.',
	};

	function errorText(error: unknown): string {
		if (error instanceof ApiError && ERROR_TEXT[error.code]) return ERROR_TEXT[error.code];
		return 'No se pudo guardar el criterio. Inténtalo de nuevo.';
	}

	function openCreate(): void {
		hapticTap();
		formError = null;
		form =
			form && form.id === null
				? null
				: {
						id: null,
						performanceId: '',
						capabilityIds: [],
						description: '',
					};
	}

	function openEdit(criterion: ExperienceCriterionDto): void {
		hapticTap();
		formError = null;
		form = {
			id: criterion.id,
			performanceId: criterion.performance_id,
			capabilityIds: [...list(criterion.capability_ids)],
			description: criterion.description,
		};
	}

	// Choosing a desempeño pre-marks the capacidad it hints at; the teacher can
	// change it.
	function choosePerformance(id: string): void {
		if (!form) return;
		form.performanceId = id;
		const hint = performances.find((performance) => performance.id === id)?.suggested_capability_id;
		if (hint && form.capabilityIds.length === 0) form.capabilityIds = [hint];
	}

	function toggleCapability(id: string): void {
		if (!form) return;
		form.capabilityIds = form.capabilityIds.includes(id)
			? form.capabilityIds.filter((item) => item !== id)
			: [...form.capabilityIds, id];
	}

	const canSave = $derived(
		!!form &&
			form.performanceId !== '' &&
			form.capabilityIds.length > 0 &&
			form.description.trim() !== ''
	);

	async function save(): Promise<void> {
		if (!form || !current || !canSave || saving) return;
		saving = true;
		formError = null;
		const body = {
			description: form.description.trim(),
			capability_ids: form.capabilityIds,
			performance_id: form.performanceId,
		};
		try {
			if (form.id) await updateCriterion(form.id, body);
			else await createCriterion(experienceId, { competency_id: current.id, ...body });
			form = null;
			await reload();
			showToast('Criterio guardado');
		} catch (error) {
			formError = errorText(error);
		} finally {
			saving = false;
		}
	}

	// ---- proposals ----

	async function accept(criterion: ExperienceCriterionDto): Promise<void> {
		hapticTap();
		try {
			await acceptCriterion(criterion.id);
			await reload();
		} catch {
			showToast('No se pudo aceptar el criterio');
		}
	}

	let deletingId = $state<string | null>(null);

	async function remove(id: string): Promise<void> {
		deletingId = null;
		try {
			await deleteCriterion(id);
			if (form?.id === id) form = null;
			await reload();
			showToast('Criterio quitado');
		} catch {
			showToast('No se pudo quitar el criterio');
		}
	}

	// ---- "✦ Generar con Mawta": only fills capacidades without a criterio ----

	let generating = $state(false);

	const sleep = (ms: number): Promise<void> => new Promise((resolve) => setTimeout(resolve, ms));

	async function poll(generationId: string): Promise<GenerationDto> {
		for (;;) {
			await sleep(1000);
			const generation = await getGeneration(generationId);
			if (generation.status === 'completed' || generation.status === 'failed') return generation;
		}
	}

	async function generate(): Promise<void> {
		if (!current || generating) return;
		hapticTap();
		generating = true;
		form = null;
		try {
			const started = await generateCriteria(experienceId, current.id);
			const done = await poll(started.id);
			if (done.status === 'failed') {
				showToast(done.error ?? 'Mawta no pudo proponer criterios esta vez');
			} else {
				await reload();
			}
		} catch {
			showToast('No se pudo generar con Mawta');
		} finally {
			generating = false;
		}
	}

	function next(): void {
		if (unseen > 0) return;
		hapticTap();
		void goto(`/class/${courseId}/plan/${experienceId}/evidences`);
	}
</script>

<svelte:head>
	<title>Criterios</title>
</svelte:head>

<TopBar back={`/class/${courseId}/plan`} useHistory />

<div class="body">
	{#if ready && experience && current}
		<p class="eyebrow">{experience.title} · Criterios</p>
		{#if experience.status === 'planificada'}
			<a class="to-summary pressable" href={`/class/${courseId}/plan/${experienceId}/summary`}>
				‹ Volver al resumen
			</a>
		{/if}

		<div class="comp-nav row">
			<button
				class="nav pressable"
				aria-label="Competencia anterior"
				disabled={compIdx === 0}
				onclick={() => go(-1)}>‹</button
			>
			<span class="grow nav-label">{compIdx + 1} de {comps.length} competencias</span>
			<button
				class="nav pressable"
				aria-label="Competencia siguiente"
				disabled={compIdx === comps.length - 1}
				onclick={() => go(1)}>›</button
			>
		</div>

		<h1 class="screen-title comp-title">{current.name}</h1>

		<div class="context-card caps">
			<p class="eyebrow caps-title">Capacidades que miran tus criterios</p>
			{#each capabilities as capability (capability.id)}
				<div class="cap-row row">
					<span class="grow cap-name">{capability.name}</span>
					<span class="cap-state" class:none={!covered.has(capability.id)}>
						{covered.has(capability.id) ? 'Con criterio' : 'Sin criterio'}
					</span>
				</div>
			{/each}
		</div>

		<div class="section">
			<p class="eyebrow">Criterios · {criteria.length}</p>
			{#if pending}
				<p class="meta help">Mawta propuso estos criterios: acéptalos o edítalos.</p>
			{/if}

			{#if criteria.length === 0}
				<div class="card empty-card">
					<p class="empty-title">Aún no hay criterios para esta competencia.</p>
					<p class="meta">
						Mawta puede proponerlos a partir de los desempeños del grado, o puedes crearlos tú.
					</p>
				</div>
			{/if}

			<div class="stack">
				{#each criteria as criterion (criterion.id)}
					{#if form && form.id === criterion.id}
						{@render editor()}
					{:else}
						<div class="card crit">
							<p class="crit-text">{criterion.description}</p>
							<p class="crit-line">
								{list(criterion.capability_ids).length > 1
									? 'Mira las capacidades'
									: 'Mira la capacidad'}
								{joinY(list(criterion.capability_ids).map(capabilityName))}.
							</p>
							{#if performanceText(criterion.performance_id)}
								<p class="crit-from">
									↳ desde: {shortText(performanceText(criterion.performance_id))}
								</p>
							{/if}
							<div class="crit-actions row">
								{#if isProposal(criterion)}
									<button class="mini go pressable" onclick={() => void accept(criterion)}>
										<Icon name="check" size={13} /> Aceptar
									</button>
								{/if}
								<button class="mini pressable" onclick={() => openEdit(criterion)}>Editar</button>
								<button
									class="mini quiet pressable"
									onclick={() => {
										hapticTap();
										deletingId = criterion.id;
									}}
								>
									<Icon name="trash" size={13} /> Quitar
								</button>
							</div>
						</div>
					{/if}
				{/each}
			</div>

			<div class="row actions">
				{#if missing.length > 0}
					<button
						class="btn-block pressable half"
						disabled={generating}
						onclick={() => void generate()}
					>
						<Icon name="sparkles" size={15} />
						{criteria.length === 0 ? 'Generar con Mawta' : 'Generar los que faltan'}
					</button>
				{/if}
				<button class="btn-block pressable half" onclick={openCreate}>
					<Icon name={form && form.id === null ? 'x' : 'plus'} size={15} />
					{form && form.id === null ? 'Cerrar' : 'Agregar criterio'}
				</button>
			</div>
			{#if generating}
				<p class="meta waiting">
					Mawta está proponiendo criterios para las capacidades sin criterio…
				</p>
			{/if}

			{#if form && form.id === null}
				{@render editor()}
			{/if}
		</div>

		<div class="footer-action">
			<button class="btn-block btn-primary pressable" disabled={unseen > 0} onclick={next}>
				Continuar con las evidencias <Icon name="chevron-right" size={16} />
			</button>
			{#if unseen > 0}
				<p class="meta footer-help">
					Revisa {unseen === 1
						? 'la competencia que falta'
						: `las ${unseen} competencias que faltan`}
					con las flechas ‹ ›.
				</p>
			{/if}
		</div>
	{:else if ready && experience}
		<p class="empty">Esta experiencia no tiene competencias.</p>
	{:else if loadError}
		<p class="empty">
			No se pudo cargar la experiencia.
			<button class="pill-light pressable" onclick={load}>Reintentar</button>
		</p>
	{/if}
</div>

{#snippet editor()}
	{#if form}
		<div class="card crit editing">
			<p class="f-label">Desempeño del grado</p>
			<select
				class="field"
				value={form.performanceId}
				onchange={(event) => choosePerformance(event.currentTarget.value)}
			>
				<option value="" disabled>Elige un desempeño</option>
				{#each performances as performance (performance.id)}
					<option value={performance.id}>{shortText(performance.text, 110)}</option>
				{/each}
			</select>

			<p class="f-label spaced">Capacidades que mira</p>
			<div class="cap-options">
				{#each capabilities as capability (capability.id)}
					<label class="cap-option">
						<input
							type="checkbox"
							checked={form.capabilityIds.includes(capability.id)}
							onchange={() => toggleCapability(capability.id)}
						/>
						<span>{capability.name}</span>
					</label>
				{/each}
			</div>

			<p class="f-label spaced">Criterio</p>
			<textarea
				class="field"
				rows="3"
				placeholder="Aterriza el desempeño a tu situación"
				bind:value={form.description}></textarea>

			{#if formError}
				<p class="form-error"><Icon name="alert" size={14} /> {formError}</p>
			{/if}

			<div class="crit-actions row">
				<button class="mini go pressable" disabled={!canSave || saving} onclick={() => void save()}>
					<Icon name="check" size={13} /> Guardar
				</button>
				<button class="mini quiet pressable" onclick={() => (form = null)}>Cancelar</button>
			</div>
		</div>
	{/if}
{/snippet}

{#if deletingId}
	<ConfirmDialog
		title="¿Quitar este criterio?"
		text="Se quita también de las evidencias que lo usan."
		confirmLabel="Quitar"
		onconfirm={() => void remove(deletingId ?? '')}
		oncancel={() => (deletingId = null)}
	/>
{/if}

<style>
	/* A competencia's name is long; the screen title shrinks to fit it. */
	.comp-title {
		font-size: 24px;
		line-height: 1.2;
	}

	.comp-nav {
		align-items: center;
		gap: var(--space-sm);
		margin: var(--space-sm) 0 var(--space-md);
	}

	.nav {
		width: 36px;
		height: 36px;
		border-radius: 50%;
		background: var(--aurora-tint);
		color: var(--aurora-deep);
		font-size: 20px;
		font-weight: 700;
		line-height: 1;
	}

	.nav:disabled {
		opacity: 0.35;
	}

	.nav-label {
		text-align: center;
		font-size: 12px;
		color: var(--text-muted);
	}

	.caps {
		margin-top: 14px;
	}

	.caps-title {
		margin: 0 0 6px;
	}

	.cap-row {
		align-items: baseline;
		gap: var(--space-sm);
		padding: 6px 0;
	}

	.cap-row + .cap-row {
		border-top: 0.5px solid var(--hair);
	}

	.cap-name {
		font-size: 13px;
		line-height: 1.4;
		color: var(--text-primary);
	}

	/* Status in words, never a chip. */
	.cap-state {
		flex-shrink: 0;
		font-size: 12px;
		color: var(--text-secondary);
	}

	.cap-state.none {
		color: var(--text-muted);
	}

	.section {
		margin-top: var(--space-xl);
	}

	.help {
		margin: -4px 0 6px;
	}

	.empty-card {
		padding: var(--space-md);
		margin-bottom: var(--space-sm);
	}

	.empty-title {
		margin: 0 0 4px;
		font-size: 14px;
		font-weight: 700;
	}

	.crit {
		padding: var(--space-md);
	}

	.crit-text {
		margin: 0;
		font-size: 14px;
		line-height: 1.45;
		color: var(--text-primary);
	}

	.crit-line {
		margin: 8px 0 0;
		font-size: 12px;
		line-height: 1.4;
		color: var(--text-secondary);
	}

	.crit-from {
		margin: 6px 0 0;
		font-size: 12px;
		line-height: 1.4;
		color: var(--text-muted);
	}

	.crit-actions {
		gap: 8px;
		margin-top: 12px;
		flex-wrap: wrap;
	}

	.mini {
		display: inline-flex;
		align-items: center;
		gap: 4px;
		padding: 7px 12px;
		border-radius: 999px;
		background: var(--aurora-tint);
		color: var(--aurora-deep);
		font-size: 12px;
		font-weight: 600;
	}

	.mini.go {
		background: var(--gradient-action);
		color: var(--on-primary);
	}

	.mini.quiet {
		background: none;
		color: var(--text-muted);
	}

	.mini:disabled {
		opacity: 0.5;
	}

	.actions {
		gap: 8px;
		margin-top: 12px;
	}

	.half {
		flex: 1;
		padding: 12px;
		font-size: 13px;
	}

	.half:disabled {
		opacity: 0.6;
	}

	.waiting {
		margin: 8px 0 0;
	}

	.editing {
		margin-top: 12px;
	}

	.f-label {
		margin: 0 0 6px;
		font-size: 12px;
		font-weight: 700;
		color: var(--text-secondary);
	}

	.f-label.spaced {
		margin-top: 14px;
	}

	.field {
		width: 100%;
		padding: 12px 14px;
		border-radius: 12px;
		border: 1px solid var(--border);
		background: var(--surface-2);
		font-family: inherit;
		font-size: 14px;
		color: var(--text-primary);
		box-sizing: border-box;
	}

	.field:focus {
		outline: none;
		border-color: var(--aurora-deep);
	}

	textarea.field {
		resize: vertical;
		line-height: 1.45;
	}

	.cap-options {
		display: flex;
		flex-direction: column;
	}

	.cap-option {
		display: flex;
		align-items: flex-start;
		gap: 10px;
		padding: 8px 0;
		font-size: 13px;
		line-height: 1.4;
		cursor: pointer;
	}

	.cap-option + .cap-option {
		border-top: 0.5px solid var(--hair);
	}

	.cap-option input {
		width: 18px;
		height: 18px;
		margin: 1px 0 0;
		flex-shrink: 0;
		accent-color: var(--aurora-deep);
	}

	.form-error {
		display: flex;
		align-items: center;
		gap: 6px;
		margin: 10px 0 0;
		font-size: 12px;
		color: var(--text-primary);
	}

	.footer-action {
		margin-top: var(--space-xl);
	}

	.footer-action .btn-primary:disabled {
		opacity: 0.5;
	}

	.footer-help {
		margin: 8px 0 0;
		text-align: center;
	}

	.empty {
		margin: var(--space-lg) 0 0;
		font-size: 13px;
		color: var(--text-muted);
	}

	/* A planned experience keeps a way back to its summary. */
	.to-summary {
		display: inline-block;
		margin: 2px 0 6px;
		font-size: 12px;
		font-weight: 600;
		color: var(--aurora-deep);
		text-decoration: none;
	}
</style>
