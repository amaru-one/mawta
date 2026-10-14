<script lang="ts">
	import {
		Action,
		Button,
		Card,
		Checkbox,
		CoverageMeter,
		Disclosure,
		EmptyState,
		ErrorNotice,
		Field,
		Icon,
		ItemActions,
		LoadingState,
		ProposalBar,
		StepNav,
	} from '$lib/design-system';
	// The criteria step of a saved experience. One competencia at a time, with
	// ‹ › between them: its capacidades say in words which ones a criterio
	// already looks at, and the criterios are the protagonists. A criterio is a
	// cycle standard landed on the situation (a grade desempeño is optional
	// support); it can look at several capacidades of its competencia and is
	// listed once. Mawta only fills gaps when asked, and "Continuar" waits until
	// every competencia was seen.
	import { onDestroy, onMount } from 'svelte';
	import { page } from '$app/state';
	import { goto } from '$app/navigation';
	import { list } from '$lib/api/client';
	import { agentUnavailable, GenerationAborted, waitForGeneration } from '$lib/api/generation';
	import { isAgentUnavailable, planningErrorText } from '$lib/api/planningErrors';
	import type {
		CurriculumCompetencyDto,
		CurriculumDto,
		ExperienceCriterionDto,
		ExperienceDto,
	} from '$lib/api/dto';
	import {
		acceptCriterion,
		createCriterion,
		deleteCriterion,
		generateCriteria,
		getClassCurriculum,
		getExperience,
		updateCriterion,
	} from '$lib/api/endpoints/planning';
	import ConfirmDialog from '$lib/components/ConfirmDialog.svelte';
	import TopBar from '$lib/components/TopBar.svelte';
	import { hapticTap } from '$lib/haptics';
	import { showToast } from '$lib/toast';

	const courseId = $derived(page.params.courseId ?? '');
	const experienceId = $derived(page.params.experienceId ?? '');

	let ready = $state(false);
	let loadError = $state(false);
	let experience = $state<ExperienceDto | null>(null);
	// Opened from the summary (or already planned): the step is a leaf of the
	// hub and "Listo" returns there, instead of walking on to the next step.
	const editing = $derived(
		page.url.searchParams.get('from') === 'summary' || experience?.status === 'planificada'
	);
	const summaryHref = $derived(`/class/${courseId}/plan/${experienceId}/summary`);
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

	// A link from the summary can name the competencia to open first.
	let requestedCompetency = page.url.searchParams.get('competency');
	$effect(() => {
		if (!requestedCompetency || comps.length === 0) return;
		const index = comps.findIndex((c) => c.id === requestedCompetency);
		if (index >= 0) compIdx = index;
		requestedCompetency = null;
	});
	let visited = $state<string[]>([]);

	const comps = $derived(list(experience?.competencies));
	const current = $derived(comps[compIdx] ?? null);
	const currentCurriculum = $derived<CurriculumCompetencyDto | null>(
		list(curriculum?.competencies).find((c) => c.id === current?.id) ?? null
	);
	const capabilities = $derived(list(currentCurriculum?.capabilities));
	const performances = $derived(list(currentCurriculum?.performances));
	const standard = $derived(currentCurriculum?.standard ?? null);
	let standardOpen = $state(false);
	let performanceOpen = $state(false);
	const criteria = $derived(
		list(experience?.criteria).filter((criterion) => criterion.competency_id === current?.id)
	);
	const covered = $derived(
		new Set(criteria.flatMap((criterion) => list(criterion.capability_ids)))
	);
	const missing = $derived(capabilities.filter((capability) => !covered.has(capability.id)));
	const pendingCount = $derived(criteria.filter(isProposal).length);
	const pending = $derived(pendingCount > 0);
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
		standardOpen = false;
		performanceOpen = false;
		compIdx = next;
	}

	// "ciclo_vi" -> "ciclo VI"
	function cycleLabel(cycle: string | null | undefined): string {
		if (!cycle) return 'ciclo';
		return cycle.startsWith('ciclo_') ? `ciclo ${cycle.slice(6).toUpperCase()}` : cycle;
	}

	function isProposal(criterion: ExperienceCriterionDto): boolean {
		return criterion.proposed_by === 'mawta' && criterion.accepted_at === null;
	}

	function capabilityName(id: string): string {
		return capabilities.find((capability) => capability.id === id)?.name ?? '';
	}

	function performanceText(id: string | null): string {
		if (!id) return '';
		return performances.find((performance) => performance.id === id)?.text ?? '';
	}

	// Every criterio carries the same anchor line: the desempeño it lands on,
	// or the cycle standard when it has none.
	function anchorOf(criterion: ExperienceCriterionDto): string {
		const text = performanceText(criterion.performance_id);
		return text ? `↳ Desempeño: ${text}` : `↳ Estándar · ${cycleLabel(curriculum?.grade.cycle)}`;
	}

	// "a", "a y b", "a, b y c"
	function joinY(items: string[]): string {
		if (items.length <= 1) return items.join('');
		return `${items.slice(0, -1).join(', ')} y ${items[items.length - 1]}`;
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

	function errorText(error: unknown): string {
		return planningErrorText(error, 'No se pudo guardar el criterio. Inténtalo de nuevo.');
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
			performanceId: criterion.performance_id ?? '',
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
		!!form && form.capabilityIds.length > 0 && form.description.trim() !== ''
	);

	async function save(): Promise<void> {
		if (!form || !current || !canSave || saving) return;
		saving = true;
		formError = null;
		const body = {
			description: form.description.trim(),
			capability_ids: form.capabilityIds,
		};
		try {
			if (form.id) {
				await updateCriterion(form.id, { ...body, performance_id: form.performanceId || null });
			} else {
				await createCriterion(experienceId, {
					competency_id: current.id,
					...body,
					...(form.performanceId ? { performance_id: form.performanceId } : {}),
				});
			}
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

	// Accepts every pending proposal of this competencia, in order.
	async function acceptOne(criterion: ExperienceCriterionDto): Promise<void> {
		hapticTap();
		try {
			await acceptCriterion(criterion.id);
			await reload();
		} catch {
			showToast('No se pudo aceptar el criterio');
		}
	}

	async function acceptAll(): Promise<void> {
		hapticTap();
		try {
			for (const criterion of criteria.filter(isProposal)) {
				await acceptCriterion(criterion.id);
			}
		} catch {
			showToast('No se pudieron aceptar todos los criterios');
		}
		await reload();
	}

	// Quitar asks first, unlike evidencias and sesiones: removing a criterio also
	// removes its tag from every evidencia that uses it, and "Deshacer" would
	// recreate the criterio without those tags.
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

	// Stops waiting for a generation when the screen is left.
	const leaving = new AbortController();
	onDestroy(() => leaving.abort());

	async function generate(): Promise<void> {
		if (!current || generating) return;
		hapticTap();
		generating = true;
		form = null;
		try {
			const started = await generateCriteria(experienceId, current.id);
			const done = await waitForGeneration(started, leaving.signal);
			if (done.status === 'failed') {
				showToast(done.error ?? 'Mawta no pudo proponer criterios esta vez');
			} else {
				await reload();
			}
		} catch (error) {
			if (error instanceof GenerationAborted) return;
			if (isAgentUnavailable(error)) agentUnavailable.set(true);
			showToast(planningErrorText(error, 'No se pudo generar con Mawta'));
		} finally {
			generating = false;
		}
	}

	function next(): void {
		if (!editing && unseen > 0) return;
		hapticTap();
		void goto(editing ? summaryHref : `/class/${courseId}/plan/${experienceId}/evidences`, {
			replaceState: true,
		});
	}
</script>

<svelte:head>
	<title>Criterios</title>
</svelte:head>
<div class="view">
	<TopBar back={editing ? summaryHref : `/class/${courseId}/plan`} />

	<div class="body">
		{#if ready && experience && current}
			<p class="eyebrow">{experience.title} · Criterios</p>

			<StepNav
				title="Revisar competencias"
				index={compIdx}
				total={comps.length}
				onprevious={() => go(-1)}
				onnext={() => go(1)}
			/>
			<h1 class="screen-title comp-title">{current.name}</h1>

			<CoverageMeter
				capabilities={capabilities.map((capability) => ({
					id: capability.id,
					label: capability.name,
					covered: covered.has(capability.id),
				}))}
			/>

			{#if standard}
				<div class="standard">
					<p class="eyebrow">Estándar · nivel esperado {cycleLabel(curriculum?.grade.cycle)}</p>
					<p id="standard-text" class="standard-text" class:clamped={!standardOpen}>
						{standard.text}
					</p>
					<button
						type="button"
						class="standard-toggle"
						aria-expanded={standardOpen}
						aria-controls="standard-text"
						onclick={() => (standardOpen = !standardOpen)}
					>
						{standardOpen ? 'Ver menos' : 'Ver completo'}
					</button>
				</div>
			{/if}

			<div class="section">
				<p class="eyebrow">Criterios · {criteria.length}</p>
				{#if pending}
					<ProposalBar
						message={`Mawta propuso ${pendingCount === 1 ? '1 criterio' : `${pendingCount} criterios`}: revísalos o acéptalos.`}
						count={pendingCount}
						label="Aceptar propuestas"
						onaccept={() => void acceptAll()}
					/>
				{/if}

				{#if criteria.length === 0}
					<Card>
						<p class="empty-title">Aún no hay criterios para esta competencia.</p>
						<p class="meta">
							Mawta puede proponerlos a partir del estándar del ciclo, o puedes crearlos tú.
						</p>
					</Card>
				{/if}

				<div class="stack">
					{#each criteria as criterion (criterion.id)}
						{#if form && form.id === criterion.id}
							{@render editor()}
						{:else}
							<Card>
								<p class="crit-text">{criterion.description}</p>
								<p class="crit-line">
									{list(criterion.capability_ids).length > 1
										? 'Mira las capacidades'
										: 'Mira la capacidad'}
									{joinY(list(criterion.capability_ids).map(capabilityName))}.
								</p>
								<p class="crit-from">{anchorOf(criterion)}</p>
								<ItemActions
									proposal={isProposal(criterion)}
									onaccept={() => void acceptOne(criterion)}
									onedit={() => openEdit(criterion)}
									onremove={() => {
										hapticTap();
										deletingId = criterion.id;
									}}
								/>
							</Card>
						{/if}
					{/each}
				</div>

				<div class="row actions">
					{#if missing.length > 0 && !$agentUnavailable}
						<Button
							variant="secondary"
							block
							class="half"
							disabled={generating}
							onclick={() => void generate()}
						>
							<Icon name="sparkles" size={15} />
							{criteria.length === 0 ? 'Generar con Mawta' : 'Generar los que faltan'}
						</Button>
					{/if}
					<Button variant="secondary" block class="half" onclick={openCreate}>
						<Icon name={form && form.id === null ? 'x' : 'plus'} size={15} />
						{form && form.id === null ? 'Cerrar' : 'Agregar criterio'}
					</Button>
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
				<Button variant="primary" block disabled={!editing && unseen > 0} onclick={next}>
					{#if editing}Listo{:else}Continuar con las evidencias <Icon
							name="chevron-right"
							size={16}
						/>{/if}
				</Button>
				{#if !editing && unseen > 0}
					<p class="meta footer-help">
						Revisa {unseen === 1
							? 'la competencia que falta'
							: `las ${unseen} competencias que faltan`}
						con las flechas ‹ ›.
					</p>
				{/if}
			</div>
		{:else if ready && experience}
			<EmptyState title="Esta experiencia no tiene competencias." />
		{:else if loadError}
			<ErrorNotice message="No se pudo cargar la experiencia." onretry={load} />
		{:else}<LoadingState label="Cargando…" />{/if}
	</div>

	{#snippet editor()}
		{#if form}
			<Card>
				<p class="f-label">Capacidades que mira</p>
				<div class="cap-options">
					{#each capabilities as capability (capability.id)}
						<Checkbox
							checked={form.capabilityIds.includes(capability.id)}
							onchange={() => toggleCapability(capability.id)}
						>
							<span>{capability.name}</span>
						</Checkbox>
					{/each}
				</div>

				<Field
					kind="textarea"
					label="Criterio"
					rows={3}
					placeholder="Concreta el estándar en tu situación"
					bind:value={form.description}
				/>

				{#if performances.length > 0}
					<Disclosure bind:open={performanceOpen}>
						{#snippet summary()}
							<span class="pick-head">
								<span class="pick-label">Desempeño del grado (opcional)</span>
								<span class="pick-value">
									{form?.performanceId ? performanceText(form.performanceId) : 'Sin desempeño'}
								</span>
							</span>
						{/snippet}
						<fieldset class="group">
							<legend class="pick-hint">
								Elige el desempeño al que se ancla el criterio, o déjalo sin desempeño.
							</legend>
							<label class="pick">
								<input
									type="radio"
									name="performance"
									value=""
									checked={form.performanceId === ''}
									onchange={() => choosePerformance('')}
								/>
								<span>Sin desempeño</span>
							</label>
							{#each performances as performance (performance.id)}
								<label class="pick">
									<input
										type="radio"
										name="performance"
										value={performance.id}
										checked={form.performanceId === performance.id}
										onchange={() => choosePerformance(performance.id)}
									/>
									<span>{performance.text}</span>
								</label>
							{/each}
						</fieldset>
					</Disclosure>
				{:else}
					<p class="meta no-perf">
						Este grado no tiene desempeños cargados para esta competencia. El criterio se basa en el
						estándar del ciclo.
					</p>
				{/if}

				{#if formError}
					<p class="mw-field__error"><Icon name="alert" size={14} /> {formError}</p>
				{/if}

				<div class="crit-actions row">
					<Action variant="main" disabled={!canSave || saving} onclick={() => void save()}>
						<Icon name="check" size={13} /> Guardar
					</Action>
					<Action variant="remove" onclick={() => (form = null)}>Cancelar</Action>
				</div>
			</Card>
		{/if}
	{/snippet}

	{#if deletingId}
		<ConfirmDialog
			title="¿Quitar este criterio?"
			description="Se quita también de las evidencias que lo usan."
			confirmLabel="Quitar"
			onconfirm={() => void remove(deletingId ?? '')}
			oncancel={() => (deletingId = null)}
		/>
	{/if}
</div>

<style>
	.comp-title {
		font-size: var(--mw-type-title-size);
		line-height: 1.2;
	}

	.standard {
		margin-top: var(--mw-space-4);
	}

	.standard-text {
		margin: 0;
		max-width: 68ch;
		font-size: var(--mw-type-small-size);
		line-height: 1.5;
		color: var(--mw-ink-secondary);
	}

	.standard-text.clamped {
		display: -webkit-box;
		-webkit-box-orient: vertical;
		-webkit-line-clamp: 3;
		line-clamp: 3;
		overflow: hidden;
	}

	.standard-toggle {
		margin: 4px 0 0;
		padding: 8px 0;
		min-height: 44px;
		border: 0;
		background: none;
		font: inherit;
		font-size: var(--mw-type-caption-size);
		font-weight: 700;
		color: var(--mw-ink);
		text-decoration: underline;
		cursor: pointer;
	}

	.section {
		margin-top: var(--mw-space-6);
	}

	.empty-title {
		margin: 0 0 4px;
		font-size: var(--mw-type-body-size);
		font-weight: 700;
	}

	.crit-text {
		margin: 0;
		font-size: var(--mw-type-body-size);
		line-height: 1.45;
		color: var(--mw-ink);
	}

	.crit-line {
		margin: 8px 0 0;
		font-size: var(--mw-type-caption-size);
		line-height: 1.4;
		color: var(--mw-ink-secondary);
	}

	.crit-from {
		margin: 6px 0 0;
		font-size: var(--mw-type-caption-size);
		line-height: 1.4;
		color: var(--mw-ink-muted);
	}

	.crit-actions {
		gap: 8px;
		margin-top: 12px;
		flex-wrap: wrap;
	}

	.actions {
		gap: 8px;
		margin-top: 12px;
	}
	.view :global(.half) {
		flex: 1;
	}

	.waiting {
		margin: 8px 0 0;
	}

	.f-label {
		margin: 0 0 6px;
		font-size: var(--mw-type-caption-size);
		font-weight: 700;
		color: var(--mw-ink-secondary);
	}

	.view :global(.field) {
		width: 100%;
	}

	.cap-options {
		display: flex;
		flex-direction: column;
	}

	.footer-action {
		margin-top: var(--mw-space-6);
	}

	.footer-help {
		margin: 8px 0 0;
		text-align: center;
	}

	.view :global(.to-summary) {
		margin: 2px 0 6px;
	}

	.pick-head {
		display: flex;
		flex-direction: column;
		gap: 2px;
		text-align: left;
	}

	.pick-label {
		font-size: var(--mw-type-caption-size);
		font-weight: 700;
		color: var(--mw-ink-secondary);
	}

	.pick-value {
		font-size: var(--mw-type-small-size);
		line-height: 1.45;
		color: var(--mw-ink);
		overflow-wrap: anywhere;
	}

	.pick-hint {
		margin: 0 0 var(--mw-space-2);
		font-size: var(--mw-type-caption-size);
		color: var(--mw-ink-muted);
	}

	.pick {
		display: flex;
		align-items: flex-start;
		gap: var(--mw-space-2);
		min-height: 44px;
		padding: var(--mw-space-2) 0;
		border-top: 1px solid var(--mw-line);
		font-size: var(--mw-type-small-size);
		line-height: 1.45;
		color: var(--mw-ink-secondary);
		cursor: pointer;
	}

	.pick input {
		margin-top: 3px;
		width: 18px;
		height: 18px;
		flex: none;
		accent-color: var(--mw-ink);
	}

	.no-perf {
		margin: var(--mw-space-2) 0 0;
		line-height: 1.45;
	}
</style>
