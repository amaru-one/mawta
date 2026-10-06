<script lang="ts">
	import {
		Action,
		Button,
		Card,
		Checkbox,
		CoverageMeter,
		EmptyState,
		Field,
		Icon,
		LoadingState,
		StepNav,
	} from '$lib/design-system';
	// The criteria step of a saved experience. One competencia at a time, with
	// ‹ › between them: its capacidades say in words which ones a criterio
	// already looks at, and the criterios are the protagonists. A criterio is a
	// grade desempeño landed on the situation; it can look at several
	// capacidades of its competencia and is listed once. Mawta only fills gaps
	// when asked, and "Continuar" waits until every competencia was seen.
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

	function performanceText(id: string | null): string {
		if (!id) return '';
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
		if (unseen > 0) return;
		hapticTap();
		void goto(`/class/${courseId}/plan/${experienceId}/evidences`);
	}
</script>

<svelte:head>
	<title>Criterios</title>
</svelte:head>
<div class="view">
	<TopBar back={`/class/${courseId}/plan`} useHistory />

	<div class="body">
		{#if ready && experience && current}
			<p class="eyebrow">{experience.title} · Criterios</p>
			{#if experience.status === 'planificada'}
				<Action variant="link" href={`/class/${courseId}/plan/${experienceId}/summary`}>
					‹ Volver al resumen
				</Action>
			{/if}

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

			<div class="section">
				<p class="eyebrow">Criterios · {criteria.length}</p>
				{#if pending}
					<p class="meta help">Mawta propuso estos criterios: acéptalos o edítalos.</p>
				{/if}

				{#if criteria.length === 0}
					<Card>
						<p class="empty-title">Aún no hay criterios para esta competencia.</p>
						<p class="meta">
							Mawta puede proponerlos a partir de los desempeños del grado, o puedes crearlos tú.
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
								{#if performanceText(criterion.performance_id)}
									<p class="crit-from">
										↳ desde: {shortText(performanceText(criterion.performance_id))}
									</p>
								{/if}
								<div class="crit-actions row">
									{#if isProposal(criterion)}
										<Action variant="main" onclick={() => void accept(criterion)}>
											<Icon name="check" size={13} /> Aceptar
										</Action>
									{/if}
									<Action variant="link" onclick={() => openEdit(criterion)}>Editar</Action>
									<Action
										variant="remove"
										onclick={() => {
											hapticTap();
											deletingId = criterion.id;
										}}
									>
										<Icon name="trash" size={13} /> Quitar
									</Action>
								</div>
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
				<Button variant="primary" block disabled={unseen > 0} onclick={next}>
					Continuar con las evidencias <Icon name="chevron-right" size={16} />
				</Button>
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
			<EmptyState title="Esta experiencia no tiene competencias." />
		{:else if loadError}
			<p class="empty">
				No se pudo cargar la experiencia.
				<Button variant="secondary" onclick={load}>Reintentar</Button>
			</p>
		{:else}<LoadingState label="Cargando…" />{/if}
	</div>

	{#snippet editor()}
		{#if form}
			<Card>
				<Field
					kind="select"
					label="Desempeño del grado"
					value={form.performanceId}
					onchange={(event) => choosePerformance(event.currentTarget.value)}
				>
					<option value="" disabled>Elige un desempeño</option>
					{#each performances as performance (performance.id)}
						<option value={performance.id}>{shortText(performance.text, 110)}</option>
					{/each}
				</Field>

				<p class="f-label spaced">Capacidades que mira</p>
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
					placeholder="Aterriza el desempeño a tu situación"
					bind:value={form.description}
				/>

				{#if formError}
					<p class="form-error"><Icon name="alert" size={14} /> {formError}</p>
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
			text="Se quita también de las evidencias que lo usan."
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

	.section {
		margin-top: var(--mw-space-6);
	}

	.help {
		margin: -4px 0 6px;
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

	.f-label.spaced {
		margin-top: 14px;
	}
	.view :global(.field) {
		width: 100%;
	}

	.cap-options {
		display: flex;
		flex-direction: column;
	}

	.form-error {
		display: flex;
		align-items: center;
		gap: 6px;
		margin: 10px 0 0;
		font-size: var(--mw-type-caption-size);
		color: var(--mw-ink);
	}

	.footer-action {
		margin-top: var(--mw-space-6);
	}

	.footer-help {
		margin: 8px 0 0;
		text-align: center;
	}

	.empty {
		margin: var(--mw-space-4) 0 0;
		font-size: var(--mw-type-small-size);
		color: var(--mw-ink-muted);
	}
	.view :global(.to-summary) {
		margin: 2px 0 6px;
	}
</style>
