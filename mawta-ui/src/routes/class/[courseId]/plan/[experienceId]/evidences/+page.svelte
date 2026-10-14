<script lang="ts">
	import {
		Action,
		Button,
		Card,
		Checkbox,
		EmptyState,
		ErrorNotice,
		Field,
		Icon,
		ItemActions,
		LoadingState,
		Notice,
		ProposalBar,
		Segmented,
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
	import { EVIDENCE_KIND_LABEL, EVIDENCE_KINDS } from '$lib/evidence';
	import type {
		EvidenceKind,
		ExperienceCompetencyRefDto,
		ExperienceCriterionDto,
		ExperienceDto,
		PlannedEvidenceDto,
		ValueScale,
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

	// How an evidencia will be valued, in the teacher's words.
	function scaleWords(evidence: PlannedEvidenceDto): string {
		return evidence.value_scale === 'ordinal'
			? 'Se valora con letras · AD, A, B, C'
			: `Se valora con nota sobre ${evidence.max_score ?? 20}`;
	}

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
		valueScale: ValueScale;
		// Kept as typed; only read when the scale is numeric.
		maxScore: string;
		criterionIds: string[];
	};

	let form = $state<EvidenceForm | null>(null);
	let saving = $state(false);
	let formError = $state<string | null>(null);
	// The maximum is validated once the teacher leaves its field, not per key.
	let maxTouched = $state(false);

	function errorText(error: unknown): string {
		return planningErrorText(error, 'No se pudo guardar la evidencia. Inténtalo de nuevo.');
	}

	function openCreate(): void {
		hapticTap();
		formError = null;
		maxTouched = false;
		form =
			form && form.id === null
				? null
				: {
						id: null,
						name: '',
						kind: 'produccion',
						valueScale: 'numeric',
						maxScore: '20',
						criterionIds: [],
					};
	}

	function openEdit(evidence: PlannedEvidenceDto): void {
		hapticTap();
		formError = null;
		maxTouched = false;
		form = {
			id: evidence.id,
			name: evidence.name,
			kind: evidence.kind,
			valueScale: evidence.value_scale,
			maxScore: String(evidence.max_score ?? 20),
			criterionIds: [...list(evidence.criterion_ids)],
		};
	}

	function toggleCriterion(id: string): void {
		if (!form) return;
		form.criterionIds = form.criterionIds.includes(id)
			? form.criterionIds.filter((item) => item !== id)
			: [...form.criterionIds, id];
	}

	// The maximum is whatever the teacher says the work is worth, in whole
	// points: the ruler on the student's screen has one tick per point.
	const maxValid = $derived(
		!!form &&
			Number.isInteger(Number(form.maxScore)) &&
			Number(form.maxScore) >= 1 &&
			Number(form.maxScore) <= 100
	);
	const canSave = $derived(
		!!form &&
			form.name.trim() !== '' &&
			form.criterionIds.length > 0 &&
			(form.valueScale === 'ordinal' || maxValid)
	);

	// What is still missing before "Guardar" can work, in the teacher's words.
	const missingText = $derived.by(() => {
		if (!form || canSave) return null;
		const parts: string[] = [];
		if (form.name.trim() === '') parts.push('un nombre');
		if (form.criterionIds.length === 0) parts.push('al menos un criterio');
		if (form.valueScale === 'numeric' && !maxValid) parts.push('una nota máxima válida');
		return `Para guardar falta ${joinY(parts)}.`;
	});

	async function save(): Promise<void> {
		if (!form || !canSave || saving) return;
		saving = true;
		formError = null;
		const body = {
			name: form.name.trim(),
			kind: form.kind,
			value_scale: form.valueScale,
			max_score: form.valueScale === 'numeric' ? Number(form.maxScore) : null,
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

	async function acceptAll(): Promise<void> {
		hapticTap();
		try {
			for (const evidence of evidences.filter(isProposal)) {
				await acceptEvidence(evidence.id);
			}
		} catch {
			showToast('No se pudieron aceptar todas las evidencias');
		}
		await reload();
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
				value_scale: evidence.value_scale,
				max_score: evidence.max_score,
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
			<h1 class="screen-title">¿Dónde observarás tus criterios?</h1>
			<p class="meta intro">
				Producciones o actuaciones de tus estudiantes. Una evidencia puede reunir criterios de
				varias competencias.
			</p>

			{#if unobservedText !== null}
				<Notice variant="attention">
					<p>
						Sin evidencia: {unobservedText}. Agrégalos a una evidencia para poder observarlos.
					</p>
				</Notice>
			{/if}

			<div class="mw-section">
				<p class="eyebrow">Evidencias · {evidences.length}</p>
				{#if pending}
					<ProposalBar
						message="Mawta propuso estas evidencias: acéptalas o edítalas."
						count={evidences.filter(isProposal).length}
						label="Aceptar propuestas"
						onaccept={() => void acceptAll()}
					/>
				{/if}

				{#if evidences.length === 0}
					<EmptyState
						title="Aún no hay evidencias."
						description="Mawta puede proponerlas a partir de tus criterios, o puedes agregarlas tú."
					/>
				{/if}

				<div class="stack">
					{#each evidences as evidence (evidence.id)}
						{#if form && form.id === evidence.id}
							{@render editor()}
						{:else}
							<Card>
								<p class="ev-name">{evidence.name}</p>
								<p class="meta ev-kind">
									{EVIDENCE_KIND_LABEL[evidence.kind]} · {scaleWords(evidence)}
								</p>
								{#if groupsOf(evidence).length > 0}
									<ul class="ev-crit">
										{#each groupsOf(evidence) as group (group.competency.id)}
											{#if comps.length > 1}
												<li class="grp mw-text mw-text--label">{group.competency.name}</li>
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
								<ItemActions
									proposal={isProposal(evidence)}
									onaccept={() => void accept(evidence)}
									onedit={() => openEdit(evidence)}
									onremove={() => void remove(evidence.id)}
								/>
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
							loading={generating}
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
					<p class="meta waiting" role="status">
						Mawta está proponiendo evidencias para tus criterios…
					</p>
				{/if}

				{#if form && form.id === null}
					{@render editor()}
				{/if}
			</div>

			<div class="mw-footer-action">
				<Button
					variant="primary"
					block
					icon={editing ? undefined : 'chevron-right'}
					iconPosition="end"
					onclick={next}
				>
					{editing ? 'Listo' : 'Continuar con las sesiones'}
				</Button>
			</div>
		{:else if loadError}
			<ErrorNotice message="No se pudo cargar la experiencia." onretry={load} />
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
					{#each EVIDENCE_KINDS as k (k)}
						<option value={k}>{EVIDENCE_KIND_LABEL[k]}</option>
					{/each}
				</Field>

				<Segmented
					label="Cómo la valorarás"
					value={form.valueScale}
					onchange={(value) => {
						if (form) form.valueScale = value as ValueScale;
					}}
					options={[
						{ value: 'numeric', label: 'Nota sobre un máximo' },
						{ value: 'ordinal', label: 'Letras · AD–C' },
					]}
				/>
				{#if form.valueScale === 'numeric'}
					<Field
						label="Nota máxima"
						type="number"
						step="1"
						min="1"
						max="100"
						help="Número entero del 1 al 100."
						error={maxTouched && !maxValid ? 'Escribe un número entero del 1 al 100.' : undefined}
						onblur={() => (maxTouched = true)}
						bind:value={form.maxScore}
					/>
				{/if}

				<fieldset class="group">
					<legend class="mw-field__label">Criterios que observarás en ella</legend>
					{#if criteria.length === 0}
						<p class="meta no-criteria">
							Esta experiencia todavía no tiene criterios: vuelve al paso anterior para crearlos.
						</p>
					{:else}
						{#each comps as competency (competency.id)}
							{#if criteriaOf(competency.id).length > 0}
								<fieldset class="group">
									{#if comps.length > 1}
										<legend class="mw-text mw-text--label">{competency.name}</legend>
									{/if}
									{#each criteriaOf(competency.id) as criterion (criterion.id)}
										<Checkbox
											checked={form.criterionIds.includes(criterion.id)}
											onchange={() => toggleCriterion(criterion.id)}
										>
											<span>{criterion.description}</span>
										</Checkbox>
									{/each}
								</fieldset>
							{/if}
						{/each}
					{/if}
				</fieldset>

				{#if formError}
					<p class="mw-field__error"><Icon name="alert" size={14} /> {formError}</p>
				{/if}

				{#if missingText}
					<p id="ev-missing" class="meta missing">{missingText}</p>
				{/if}

				<div class="mw-btn-row">
					<Action
						variant="main"
						disabled={!canSave || saving}
						aria-describedby={missingText ? 'ev-missing' : undefined}
						onclick={() => void save()}
					>
						<Icon name="check" size={13} /> Guardar
					</Action>
					<Action variant="neutral" onclick={() => (form = null)}>Cancelar</Action>
				</div>
			</Card>
		{/if}
	{/snippet}
</div>

<style>
	.intro {
		margin: 10px 0 0;
		line-height: 1.45;
	}

	.stack {
		display: flex;
		flex-direction: column;
		gap: var(--mw-space-2);
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
		margin: var(--mw-space-2) 0 2px;
	}

	.ev-crit .crit-row {
		display: flex;
		padding: 5px 0;
		font-size: var(--mw-type-small-size);
		line-height: 1.4;
		color: var(--mw-ink-secondary);
	}

	.ev-crit .crit-row + .crit-row {
		border-top: 1px solid var(--mw-line);
	}

	.view :global(.half) {
		flex: 1 1 150px;
	}

	.waiting {
		margin: 8px 0 0;
	}

	.group {
		margin: var(--mw-space-4) 0 0;
		padding: 0;
		border: 0;
		min-width: 0;
	}

	.group legend {
		padding: 0;
		margin-bottom: var(--mw-space-2);
	}

	.missing {
		margin: var(--mw-space-2) 0 0;
	}
	.view :global(.field) {
		width: 100%;
	}

	.no-criteria {
		margin: 0;
		line-height: 1.45;
	}

	.view :global(.to-summary) {
		margin: 2px 0 6px;
	}
</style>
