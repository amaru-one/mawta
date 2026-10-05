<script lang="ts">
	// The evidences step of a saved experience: where the teacher will observe
	// the criteria. An evidencia is a producción, an actuación or a prueba
	// escrita, and it can gather criteria of several competencias at once.
	// Mawta only fills gaps when asked; every proposal waits for the teacher.
	import { onMount } from 'svelte';
	import { page } from '$app/state';
	import { goto } from '$app/navigation';
	import { ApiError, list } from '$lib/api/client';
	import type {
		EvidenceKind,
		ExperienceCompetencyRefDto,
		ExperienceCriterionDto,
		ExperienceDto,
		GenerationDto,
		PlannedEvidenceDto,
	} from '$lib/api/dto';
	import {
		acceptEvidence,
		createEvidence,
		deleteEvidence,
		generateEvidences,
		getExperience,
		getGeneration,
		updateEvidence,
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

	// The contract's codes, in the screen's own words.
	const ERROR_TEXT: Record<string, string> = {
		criterion_other_experience: 'Uno de los criterios no es de esta experiencia.',
	};

	function errorText(error: unknown): string {
		if (error instanceof ApiError && ERROR_TEXT[error.code]) return ERROR_TEXT[error.code];
		return 'No se pudo guardar la evidencia. Inténtalo de nuevo.';
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

	let deletingId = $state<string | null>(null);

	async function remove(id: string): Promise<void> {
		deletingId = null;
		const target = evidences.find((evidence) => evidence.id === id);
		if (!target) return;
		try {
			await deleteEvidence(id);
			if (form?.id === id) form = null;
			await reload();
			showToast('Evidencia quitada', {
				onUndo: () => void restore(target),
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

	const sleep = (ms: number): Promise<void> => new Promise((resolve) => setTimeout(resolve, ms));

	async function poll(generationId: string): Promise<GenerationDto> {
		for (;;) {
			await sleep(1000);
			const generation = await getGeneration(generationId);
			if (generation.status === 'completed' || generation.status === 'failed') return generation;
		}
	}

	async function generate(): Promise<void> {
		if (generating) return;
		hapticTap();
		generating = true;
		form = null;
		try {
			const started = await generateEvidences(experienceId);
			const done = await poll(started.id);
			if (done.status === 'failed') {
				showToast(done.error ?? 'Mawta no pudo proponer evidencias esta vez');
			} else {
				await reload();
				showToast('Mawta propuso evidencias');
			}
		} catch {
			showToast('No se pudo generar con Mawta');
		} finally {
			generating = false;
		}
	}

	function next(): void {
		hapticTap();
		void goto(`/class/${courseId}/plan/${experienceId}/sessions`);
	}
</script>

<svelte:head>
	<title>Evidencias</title>
</svelte:head>

<TopBar back={`/class/${courseId}/plan/${experienceId}/criteria`} useHistory />

<div class="body">
	{#if ready && experience}
		<p class="eyebrow">{experience.title} · Evidencias</p>
		<h1 class="screen-title sm">¿Dónde observarás tus criterios?</h1>
		<p class="meta intro">
			Producciones o actuaciones de tus estudiantes. Una evidencia puede reunir criterios de varias
			competencias.
		</p>

		{#if unobservedText !== null}
			<div class="notice">
				<Icon name="alert" size={16} />
				<p class="grow notice-text">
					Sin evidencia: {unobservedText}. Agrégalos a una evidencia para poder observarlos.
				</p>
			</div>
		{/if}

		<div class="section">
			<p class="eyebrow">Evidencias · {evidences.length}</p>
			{#if pending}
				<p class="meta help">Mawta propuso estas evidencias: acéptalas o edítalas.</p>
			{/if}

			{#if evidences.length === 0}
				<div class="card empty-card">
					<p class="empty-title">Aún no hay evidencias.</p>
					<p class="meta">
						Mawta puede proponerlas a partir de tus criterios, o puedes agregarlas tú.
					</p>
				</div>
			{/if}

			<div class="stack">
				{#each evidences as evidence (evidence.id)}
					{#if form && form.id === evidence.id}
						{@render editor()}
					{:else}
						<div class="card ev">
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
									<button class="mini go pressable" onclick={() => void accept(evidence)}>
										<Icon name="check" size={13} /> Aceptar
									</button>
								{/if}
								<button class="mini pressable" onclick={() => openEdit(evidence)}>Editar</button>
								<button
									class="mini quiet pressable"
									onclick={() => {
										hapticTap();
										deletingId = evidence.id;
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
				<button
					class="btn-block pressable half"
					disabled={generating}
					onclick={() => void generate()}
				>
					<Icon name="sparkles" size={15} />
					{evidences.length === 0 ? 'Generar con Mawta' : 'Generar más'}
				</button>
				<button class="btn-block pressable half" onclick={openCreate}>
					<Icon name={form && form.id === null ? 'x' : 'plus'} size={15} />
					{form && form.id === null ? 'Cerrar' : 'Agregar evidencia'}
				</button>
			</div>
			{#if generating}
				<p class="meta waiting">Mawta está proponiendo evidencias para tus criterios…</p>
			{/if}

			{#if form && form.id === null}
				{@render editor()}
			{/if}
		</div>

		<div class="footer-action">
			<button class="btn-block btn-primary pressable" onclick={next}>
				Continuar con las sesiones <Icon name="chevron-right" size={16} />
			</button>
		</div>
	{:else if loadError}
		<p class="empty">
			No se pudo cargar la experiencia.
			<button class="pill-light pressable" onclick={load}>Reintentar</button>
		</p>
	{/if}
</div>

{#snippet editor()}
	{#if form}
		<div class="card ev editing">
			<p class="f-label">Nombre</p>
			<input
				class="field"
				type="text"
				placeholder="Ej.: Hoja de cuentas de la tiendita"
				bind:value={form.name}
			/>

			<p class="f-label spaced">Tipo</p>
			<select class="field" bind:value={form.kind}>
				<option value="produccion">Producción</option>
				<option value="actuacion">Actuación</option>
				<option value="prueba_escrita">Prueba escrita</option>
			</select>

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
							<label class="crit-option">
								<input
									type="checkbox"
									checked={form.criterionIds.includes(criterion.id)}
									onchange={() => toggleCriterion(criterion.id)}
								/>
								<span>{shortText(criterion.description, 90)}</span>
							</label>
						{/each}
					{/if}
				{/each}
			{/if}

			{#if formError}
				<p class="form-error"><Icon name="alert" size={14} /> {formError}</p>
			{/if}

			<div class="ev-actions row">
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
		title="¿Quitar esta evidencia?"
		text="La sesión donde estaba ubicada la conserva, sin la evidencia."
		confirmLabel="Quitar"
		onconfirm={() => void remove(deletingId ?? '')}
		oncancel={() => (deletingId = null)}
	/>
{/if}

<style>
	/* The question is long; the title shrinks as the criteria screen's does. */
	.screen-title.sm {
		font-size: 24px;
	}

	.intro {
		margin: 10px 0 0;
		line-height: 1.45;
	}

	.notice {
		display: flex;
		align-items: flex-start;
		gap: var(--space-sm);
		background: var(--bg-danger);
		border-radius: var(--radius);
		padding: var(--space-sm) var(--space-md);
		margin-top: var(--space-md);
	}

	.notice-text {
		margin: 0;
		font-size: 13px;
		line-height: 1.45;
		color: var(--text-primary);
	}

	.section {
		margin-top: var(--space-xl);
	}

	.help {
		margin: -4px 0 6px;
	}

	.stack {
		display: flex;
		flex-direction: column;
		gap: var(--space-sm);
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

	.ev {
		padding: var(--space-md);
	}

	.ev-name {
		margin: 0;
		font-size: 14px;
		font-weight: 700;
		line-height: 1.35;
		color: var(--text-primary);
	}

	.ev-kind {
		margin: 2px 0 0;
	}

	.ev-none {
		margin: 8px 0 0;
	}

	/* The criteria an evidencia gathers, as text rows grouped by competencia. */
	.ev-crit {
		margin: 10px 0 0;
		padding: 0;
		list-style: none;
	}

	.ev-crit .grp {
		margin: 8px 0 2px;
		font-family: var(--font-mono);
		font-size: 10px;
		letter-spacing: 0.08em;
		text-transform: uppercase;
		color: var(--text-muted);
	}

	.ev-crit .crit-row {
		display: flex;
		padding: 5px 0;
		border-top: 0.5px solid var(--hair);
		font-size: 12.5px;
		line-height: 1.4;
		color: var(--text-secondary);
	}

	.ev-actions {
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

	.grp-label {
		margin: 8px 0 4px;
	}

	.no-criteria {
		margin: 0;
		line-height: 1.45;
	}

	.crit-option {
		display: flex;
		align-items: flex-start;
		gap: 10px;
		padding: 8px 0;
		font-size: 13px;
		line-height: 1.4;
		cursor: pointer;
	}

	.crit-option + .crit-option {
		border-top: 0.5px solid var(--hair);
	}

	.crit-option input {
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

	.empty {
		margin: var(--space-lg) 0 0;
		font-size: 13px;
		color: var(--text-muted);
	}
</style>
