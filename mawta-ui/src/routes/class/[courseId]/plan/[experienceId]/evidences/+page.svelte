<script lang="ts">
	import {
		Action,
		Button,
		Card,
		Checkbox,
		Field,
		Icon,
		LoadingState,
		Notice,
	} from '$lib/design-system';
	// The evidences step of a saved experience: where the teacher will observe
	// the criteria. An evidencia is a producción, an actuación or a prueba
	// escrita, and it can gather criteria of several competencias at once.
	// Mawta only fills gaps when asked; every proposal waits for the teacher.
	import { onDestroy, onMount } from 'svelte';
	import { page } from '$app/state';
	import { goto } from '$app/navigation';
	import { list } from '$lib/api/client';
	import { agentUnavailable, GenerationAborted, waitForGeneration } from '$lib/api/generation';
	import { isAgentUnavailable, planningErrorText } from '$lib/api/planningErrors';
	import type {
		EvidenceKind,
		ExperienceCompetencyRefDto,
		ExperienceCriterionDto,
		ExperienceDto,
		PlannedEvidenceDto,
	} from '$lib/api/dto';
	import {
		acceptEvidence,
		createEvidence,
		deleteEvidence,
		generateEvidences,
		getExperience,
		updateEvidence,
	} from '$lib/api/endpoints/planning';
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

	async function load(): Promise<void> {
		ready = false;
		loadError = false;
		try {
			experience = await getExperience(experienceId);
			ready = true;
		} catch {
			loadError = true;
		}
	}

	// After a write only the experience changes.
	async function reload(): Promise<void> {
		try {
			experience = await getExperience(experienceId);
		} catch {
			showToast('No se pudo actualizar la experiencia');
		}
	}

	onMount(load);

	// ---- what the screen shows ----

	const comps = $derived(list(experience?.competencies));
	const criteria = $derived(list(experience?.criteria));
	const evidences = $derived(list(experience?.evidences));
	const pending = $derived(evidences.some(isProposal));

	function isProposal(evidence: PlannedEvidenceDto): boolean {
		return evidence.proposed_by === 'mawta' && evidence.accepted_at === null;
	}

	// The contract's kinds, in the screen's own words.
	const KIND_WORDS: Record<EvidenceKind, string> = {
		produccion: 'Producción',
		actuacion: 'Actuación',
		prueba_escrita: 'Prueba escrita',
	};

	function criteriaOf(competencyId: string): ExperienceCriterionDto[] {
		return criteria.filter((criterion) => criterion.competency_id === competencyId);
	}

	type CritGroup = {
		competency: ExperienceCompetencyRefDto;
		criteria: ExperienceCriterionDto[];
	};

	// An evidencia's criteria, grouped by competencia in the experience's own
	// order — text rows, never chips.
	function groupsOf(evidence: PlannedEvidenceDto): CritGroup[] {
		const ids = new Set(list(evidence.criterion_ids));
		return comps
			.map((competency) => ({
				competency,
				criteria: criteriaOf(competency.id).filter((criterion) => ids.has(criterion.id)),
			}))
			.filter((group) => group.criteria.length > 0);
	}

	// Criteria no evidencia observes yet — a warning, never a block. Counted
	// per competencia so it stays one readable sentence.
	const unobservedText = $derived.by(() => {
		if (evidences.length === 0) return null;
		const observed = new Set(evidences.flatMap((evidence) => list(evidence.criterion_ids)));
		const parts: string[] = [];
		for (const competency of comps) {
			const own = criteriaOf(competency.id);
			const missing = own.filter((criterion) => !observed.has(criterion.id)).length;
			if (missing === 0) continue;
			const word = missing === 1 ? 'criterio' : 'criterios';
			parts.push(`${missing} ${word} de ${competency.name}`);
		}
		return parts.length > 0 ? joinY(parts) : null;
	});

	function shortText(text: string, max = 80): string {
		if (text.length <= max) return text;
		return `${text.slice(0, max).replace(/\s+\S*$/, '')}…`;
	}

	// "a", "a y b", "a, b y c"
	function joinY(items: string[]): string {
		if (items.length <= 1) return items.join('');
		return `${items.slice(0, -1).join(', ')} y ${items[items.length - 1]}`;
	}

	// ---- create and edit ----

	type EvidenceForm = {
		id: string | null;
		name: string;
		kind: EvidenceKind;
		criterionIds: string[];
	};

	let form = $state<EvidenceForm | null>(null);
	let saving = $state(false);
	let formError = $state<string | null>(null);

	function errorText(error: unknown): string {
		return planningErrorText(error, 'No se pudo guardar la evidencia. Inténtalo de nuevo.');
	}

	function openCreate(): void {
		hapticTap();
		formError = null;
		form =
			form && form.id === null
				? null
				: { id: null, name: '', kind: 'produccion', criterionIds: [] };
	}

	function openEdit(evidence: PlannedEvidenceDto): void {
		hapticTap();
		formError = null;
		form = {
			id: evidence.id,
			name: evidence.name,
			kind: evidence.kind,
			criterionIds: [...list(evidence.criterion_ids)],
		};
	}

	function toggleCriterion(id: string): void {
		if (!form) return;
		form.criterionIds = form.criterionIds.includes(id)
			? form.criterionIds.filter((item) => item !== id)
			: [...form.criterionIds, id];
	}

	const canSave = $derived(!!form && form.name.trim() !== '' && form.criterionIds.length > 0);

	async function save(): Promise<void> {
		if (!form || !canSave || saving) return;
		saving = true;
		formError = null;
		const body = {
			name: form.name.trim(),
			kind: form.kind,
			criterion_ids: form.criterionIds,
		};
		try {
			if (form.id) await updateEvidence(form.id, body);
			else await createEvidence(experienceId, body);
			form = null;
			await reload();
			showToast('Evidencia guardada');
		} catch (error) {
			formError = errorText(error);
		} finally {
			saving = false;
		}
	}

	// ---- proposals ----

	async function accept(evidence: PlannedEvidenceDto): Promise<void> {
		hapticTap();
		try {
			await acceptEvidence(evidence.id);
			await reload();
		} catch {
			showToast('No se pudo aceptar la evidencia');
		}
	}

	// ---- remove, with "Deshacer" ----

	// No confirmation: "Deshacer" in the toast is the way back.
	async function remove(id: string): Promise<void> {
		hapticTap();
		const target = evidences.find((evidence) => evidence.id === id);
		if (!target) return;
		try {
			await deleteEvidence(id);
			if (form?.id === id) form = null;
			await reload();
			showToast('Evidencia quitada', {
				onUndo: () => void restore(target),
				undoLabel: 'Deshacer',
				durationMs: 7000,
			});
		} catch {
			showToast('No se pudo quitar la evidencia');
		}
	}

	// "Deshacer" recreates the evidencia with the same fields, including its
	// placement when the session entry still exists.
	async function restore(evidence: PlannedEvidenceDto): Promise<void> {
		try {
			await createEvidence(experienceId, {
				name: evidence.name,
				kind: evidence.kind,
				criterion_ids: [...list(evidence.criterion_ids)],
				session_date: evidence.session_date,
			});
			await reload();
		} catch {
			showToast('No se pudo restaurar la evidencia');
		}
	}

	// ---- "✦ Generar con Mawta": only fills criteria nothing observes ----

	let generating = $state(false);

	// Stops waiting for a generation when the screen is left.
	const leaving = new AbortController();
	onDestroy(() => leaving.abort());

	async function generate(): Promise<void> {
		if (generating) return;
		hapticTap();
		generating = true;
		form = null;
		try {
			const started = await generateEvidences(experienceId);
			const done = await waitForGeneration(started, leaving.signal);
			if (done.status === 'failed') {
				showToast(done.error ?? 'Mawta no pudo proponer evidencias esta vez');
			} else {
				await reload();
				showToast('Mawta propuso evidencias');
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
		hapticTap();
		void goto(editing ? summaryHref : `/class/${courseId}/plan/${experienceId}/sessions`, {
			replaceState: true,
		});
	}
</script>

<svelte:head>
	<title>Evidencias</title>
</svelte:head>
<div class="view">
	<TopBar back={editing ? summaryHref : `/class/${courseId}/plan/${experienceId}/criteria`} />

	<div class="body">
		{#if ready && experience}
			<p class="eyebrow">{experience.title} · Evidencias</p>
			<h1 class="screen-title sm">¿Dónde observarás tus criterios?</h1>
			<p class="meta intro">
				Producciones o actuaciones de tus estudiantes. Una evidencia puede reunir criterios de
				varias competencias.
			</p>

			{#if unobservedText !== null}
				<Notice variant="attention">
					<p class="grow notice-text">
						Sin evidencia: {unobservedText}. Agrégalos a una evidencia para poder observarlos.
					</p>
				</Notice>
			{/if}

			<div class="section">
				<p class="eyebrow">Evidencias · {evidences.length}</p>
				{#if pending}
					<p class="meta help">Mawta propuso estas evidencias: acéptalas o edítalas.</p>
				{/if}

				{#if evidences.length === 0}
					<Card>
						<p class="empty-title">Aún no hay evidencias.</p>
						<p class="meta">
							Mawta puede proponerlas a partir de tus criterios, o puedes agregarlas tú.
						</p>
					</Card>
				{/if}

				<div class="stack">
					{#each evidences as evidence (evidence.id)}
						{#if form && form.id === evidence.id}
							{@render editor()}
						{:else}
							<Card>
								<p class="ev-name">{evidence.name}</p>
								<p class="meta ev-kind">{KIND_WORDS[evidence.kind]}</p>
								{#if groupsOf(evidence).length > 0}
									<ul class="ev-crit">
										{#each groupsOf(evidence) as group (group.competency.id)}
											{#if comps.length > 1}
												<li class="grp">{group.competency.name}</li>
											{/if}
											{#each group.criteria as criterion (criterion.id)}
												<li class="crit-row">
													<span class="grow">{criterion.description}</span>
												</li>
											{/each}
										{/each}
									</ul>
								{:else}
									<p class="meta ev-none">Sin criterios: elige cuáles observarás.</p>
								{/if}
								<div class="ev-actions row">
									{#if isProposal(evidence)}
										<Action variant="main" onclick={() => void accept(evidence)}>
											<Icon name="check" size={13} /> Aceptar
										</Action>
									{/if}
									<Action variant="link" onclick={() => openEdit(evidence)}>Editar</Action>
									<Action variant="remove" onclick={() => void remove(evidence.id)}>
										<Icon name="trash" size={13} /> Quitar
									</Action>
								</div>
							</Card>
						{/if}
					{/each}
				</div>

				<div class="row actions">
					<!-- Evidences are proposed from the criteria: none, nothing to propose. -->
					{#if criteria.length > 0 && !$agentUnavailable}
						<Button
							variant="secondary"
							block
							class="half"
							disabled={generating}
							onclick={() => void generate()}
						>
							<Icon name="sparkles" size={15} />
							{evidences.length === 0 ? 'Generar con Mawta' : 'Generar más'}
						</Button>
					{/if}
					<Button variant="secondary" block class="half" onclick={openCreate}>
						<Icon name={form && form.id === null ? 'x' : 'plus'} size={15} />
						{form && form.id === null ? 'Cerrar' : 'Agregar evidencia'}
					</Button>
				</div>
				{#if generating}
					<p class="meta waiting">Mawta está proponiendo evidencias para tus criterios…</p>
				{/if}

				{#if form && form.id === null}
					{@render editor()}
				{/if}
			</div>

			<div class="footer-action">
				<Button variant="primary" block onclick={next}>
					{#if editing}Listo{:else}Continuar con las sesiones <Icon
							name="chevron-right"
							size={16}
						/>{/if}
				</Button>
			</div>
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
					label="Nombre"
					type="text"
					placeholder="Ej.: Hoja de cuentas de la tiendita"
					bind:value={form.name}
				/>

				<Field kind="select" label="Tipo" bind:value={form.kind}>
					<option value="produccion">Producción</option>
					<option value="actuacion">Actuación</option>
					<option value="prueba_escrita">Prueba escrita</option>
				</Field>

				<p class="f-label spaced">Criterios que observarás en ella</p>
				{#if criteria.length === 0}
					<p class="meta no-criteria">
						Esta experiencia todavía no tiene criterios: vuelve al paso anterior para crearlos.
					</p>
				{:else}
					{#each comps as competency (competency.id)}
						{#if criteriaOf(competency.id).length > 0}
							<p class="meta grp-label">{competency.name}</p>
							{#each criteriaOf(competency.id) as criterion (criterion.id)}
								<Checkbox
									checked={form.criterionIds.includes(criterion.id)}
									onchange={() => toggleCriterion(criterion.id)}
								>
									<span>{shortText(criterion.description, 90)}</span>
								</Checkbox>
							{/each}
						{/if}
					{/each}
				{/if}

				{#if formError}
					<p class="form-error"><Icon name="alert" size={14} /> {formError}</p>
				{/if}

				<div class="ev-actions row">
					<Action variant="main" disabled={!canSave || saving} onclick={() => void save()}>
						<Icon name="check" size={13} /> Guardar
					</Action>
					<Action variant="remove" onclick={() => (form = null)}>Cancelar</Action>
				</div>
			</Card>
		{/if}
	{/snippet}
</div>

<style>
	.screen-title.sm {
		font-size: var(--mw-type-title-size);
	}

	.intro {
		margin: 10px 0 0;
		line-height: 1.45;
	}

	.notice-text {
		margin: 0;
		font-size: var(--mw-type-small-size);
		line-height: 1.45;
		color: var(--mw-ink);
	}

	.section {
		margin-top: var(--mw-space-6);
	}

	.help {
		margin: -4px 0 6px;
	}

	.stack {
		display: flex;
		flex-direction: column;
		gap: var(--mw-space-2);
	}

	.empty-title {
		margin: 0 0 4px;
		font-size: var(--mw-type-body-size);
		font-weight: 700;
	}

	.ev-name {
		margin: 0;
		font-size: var(--mw-type-body-size);
		font-weight: 700;
		line-height: 1.35;
		color: var(--mw-ink);
	}

	.ev-kind {
		margin: 2px 0 0;
	}

	.ev-none {
		margin: 8px 0 0;
	}

	.ev-crit {
		margin: 10px 0 0;
		padding: 0;
		list-style: none;
	}

	.ev-crit .grp {
		margin: 8px 0 2px;
		font-family: var(--mw-font-sans);
		font-size: var(--mw-type-label-size);
		letter-spacing: 0.04em;
		text-transform: uppercase;
		color: var(--mw-ink-muted);
	}

	.ev-crit .crit-row {
		display: flex;
		padding: 5px 0;
		border-top: 1px solid var(--mw-line);
		font-size: 12.5px;
		line-height: 1.4;
		color: var(--mw-ink-secondary);
	}

	.ev-actions {
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

	.grp-label {
		margin: 8px 0 4px;
	}

	.no-criteria {
		margin: 0;
		line-height: 1.45;
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

	.empty {
		margin: var(--mw-space-4) 0 0;
		font-size: var(--mw-type-small-size);
		color: var(--mw-ink-muted);
	}
	.view :global(.to-summary) {
		margin: 2px 0 6px;
	}
</style>
