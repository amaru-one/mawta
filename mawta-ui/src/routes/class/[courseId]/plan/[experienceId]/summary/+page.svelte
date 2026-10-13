<script lang="ts">
	import { Action, Button, Context, Icon, LoadingState, Notice } from '$lib/design-system';
	import { pendingCounts } from '$lib/planning/pending';
	// "Revisar y guardar": a compact summary of the experience and its notes.
	// Notes never block: a capacidad without a criterio or proposals still to
	// review are said, each linking to its step, and the teacher can save
	// anyway. A planned experience opens here from "Tu trimestre"; every step is
	// reachable from it, and it can be deleted.
	import { onMount } from 'svelte';
	import { page } from '$app/state';
	import { goto } from '$app/navigation';
	import { list } from '$lib/api/client';
	import { planningErrorText } from '$lib/api/planningErrors';
	import type { CurriculumDto, ExperienceDto, WarningDto } from '$lib/api/dto';
	import {
		confirmExperience,
		deleteExperience,
		getClassCurriculum,
		getExperience,
	} from '$lib/api/endpoints/planning';
	import ConfirmDialog from '$lib/components/ConfirmDialog.svelte';
	import TopBar from '$lib/components/TopBar.svelte';
	import { hapticTap } from '$lib/haptics';
	import { showToast } from '$lib/toast';

	const courseId = $derived(page.params.courseId ?? '');
	const experienceId = $derived(page.params.experienceId ?? '');
	const base = $derived(`/class/${courseId}/plan/${experienceId}`);

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

	onMount(load);

	const planned = $derived(experience?.status === 'planificada');
	const comps = $derived(list(experience?.competencies));
	const criteria = $derived(list(experience?.criteria));
	const evidences = $derived(list(experience?.evidences));
	const sessions = $derived(list(experience?.sessions));
	const dates = $derived(list(experience?.class_dates));
	const warnings = $derived(list(experience?.warnings));

	const placed = $derived(evidences.filter((evidence) => evidence.session_date).length);

	function capabilitiesOf(competencyId: string): { id: string; name: string }[] {
		const competency = list(curriculum?.competencies).find((c) => c.id === competencyId);
		return list(competency?.capabilities);
	}

	// Counted like the server counts coverage (and the warnings below): only
	// accepted criteria. A pending proposal is not yet the teacher's, so it is
	// shown apart instead of filling the count.
	function coveredOf(competencyId: string): number {
		const covered = new Set(
			criteria
				.filter(
					(criterion) => criterion.competency_id === competencyId && criterion.accepted_at !== null
				)
				.flatMap((criterion) => list(criterion.capability_ids))
		);
		return capabilitiesOf(competencyId).filter((capability) => covered.has(capability.id)).length;
	}

	function pendingOf(competencyId: string): number {
		return criteria.filter(
			(criterion) => criterion.competency_id === competencyId && criterion.accepted_at === null
		).length;
	}

	const missingCapabilities = $derived(
		warnings
			.filter(
				(warning): warning is Extract<WarningDto, { code: 'capability_without_criterion' }> =>
					warning.code === 'capability_without_criterion'
			)
			.map((warning) => {
				const name =
					capabilitiesOf(warning.competency_id).find((c) => c.id === warning.capability_id)?.name ??
					'';
				return name;
			})
			.filter(Boolean)
	);

	// Evidence per competencia is counted over the whole term (the conclusion
	// counts it that way), so these warnings name the competencia and the count.
	function competencyName(competencyId: string): string {
		return list(experience?.competencies).find((c) => c.id === competencyId)?.name ?? '';
	}

	const thinCompetencies = $derived(
		warnings.filter(
			(warning): warning is Extract<WarningDto, { code: 'competency_few_evidences' }> =>
				warning.code === 'competency_few_evidences'
		)
	);

	const singleKindCompetencies = $derived(
		warnings.filter(
			(warning): warning is Extract<WarningDto, { code: 'competency_single_kind' }> =>
				warning.code === 'competency_single_kind'
		)
	);

	const pendingBy = $derived(pendingCounts(experience));

	// "15 jun – 10 jul"
	const MONTHS = [
		'ene',
		'feb',
		'mar',
		'abr',
		'may',
		'jun',
		'jul',
		'ago',
		'sep',
		'oct',
		'nov',
		'dic',
	];

	function fmtDate(date: string): string {
		const [, m, d] = date.split('-').map(Number);
		return `${d} ${MONTHS[(m ?? 1) - 1]}`;
	}

	// ---- save ----

	let saving = $state(false);

	async function save(): Promise<void> {
		hapticTap();
		if (planned) {
			void goto(`/class/${courseId}/plan`, { replaceState: true });
			return;
		}
		if (saving) return;
		saving = true;
		try {
			await confirmExperience(experienceId);
			showToast('Experiencia guardada');
			void goto(`/class/${courseId}/plan`, { replaceState: true });
		} catch (error) {
			showToast(planningErrorText(error, 'No se pudo guardar la experiencia'));
		} finally {
			saving = false;
		}
	}

	// ---- delete ----

	let confirmingDelete = $state(false);

	async function remove(): Promise<void> {
		confirmingDelete = false;
		try {
			await deleteExperience(experienceId);
			showToast('Experiencia eliminada');
			void goto(`/class/${courseId}/plan`, { replaceState: true });
		} catch (error) {
			showToast(planningErrorText(error, 'No se pudo eliminar la experiencia'));
		}
	}
</script>

<svelte:head>
	<title>Revisar y guardar</title>
</svelte:head>
<div class="view">
	<TopBar back={`/class/${courseId}/plan`} />

	<div class="body">
		{#if ready && experience}
			<p class="eyebrow">{planned ? 'Experiencia planificada' : 'Revisar y guardar'}</p>
			<h1 class="screen-title title">{experience.title}</h1>
			<p class="screen-sub">
				{fmtDate(experience.starts_on)} – {fmtDate(experience.ends_on)} · {dates.length} clases
			</p>

			{#if experience.situation_text}
				<p class="situation">{experience.situation_text}</p>
			{:else}
				<p class="situation muted">Todavía sin situación significativa.</p>
			{/if}
			{#if experience.context_text}
				<p class="situation">Evento o contexto: {experience.context_text}</p>
			{/if}

			<Context>
				{#each comps as competency (competency.id)}
					<a
						class="sum-row row pressable"
						href={`${base}/criteria?from=summary`}
						data-sveltekit-replacestate
						onclick={hapticTap}
					>
						<span class="grow">{competency.name}</span>
						<span class="sum-value">
							{coveredOf(competency.id)} de {capabilitiesOf(competency.id).length} capacidades con criterio{#if pendingOf(competency.id) > 0}
								· {pendingOf(competency.id)} por revisar{/if}
						</span>
					</a>
				{/each}
				<a
					class="sum-row row pressable"
					href={`${base}/criteria?from=summary`}
					data-sveltekit-replacestate
					onclick={hapticTap}
				>
					<span class="grow">Criterios</span>
					<span class="sum-value">{criteria.length}</span>
				</a>
				<a
					class="sum-row row pressable"
					href={`${base}/evidences?from=summary`}
					data-sveltekit-replacestate
					onclick={hapticTap}
				>
					<span class="grow">Evidencias</span>
					<span class="sum-value">{evidences.length} · {placed} ubicadas en sesiones</span>
				</a>
				<a
					class="sum-row row pressable"
					href={`${base}/sessions?from=summary`}
					data-sveltekit-replacestate
					onclick={hapticTap}
				>
					<span class="grow">Sesiones</span>
					<span class="sum-value">{sessions.length} de {dates.length} fechas</span>
				</a>
			</Context>

			{#if missingCapabilities.length > 0}
				<Notice variant="attention"
					><a
						href={`${base}/criteria?from=summary`}
						data-sveltekit-replacestate
						onclick={hapticTap}
					>
						<span class="grow notice-text">
							{missingCapabilities.length === 1
								? '1 capacidad sin criterio'
								: `${missingCapabilities.length} capacidades sin criterio`}: {missingCapabilities.join(
								', '
							)}. Puedes guardar igual: es un aviso, no un bloqueo.
						</span>
					</a></Notice
				>
			{/if}
			{#each thinCompetencies as warning (warning.competency_id)}
				<Notice variant="attention"
					><a
						href={`${base}/evidences?from=summary`}
						data-sveltekit-replacestate
						onclick={hapticTap}
					>
						<span class="grow notice-text">
							{competencyName(warning.competency_id)}: {warning.count === 1
								? '1 evidencia'
								: `${warning.count} evidencias`} en el trimestre. Mawta necesita al menos 2 para proponer
							su conclusión. Agrega otra aquí o en otra experiencia. Puedes guardar igual.
						</span>
					</a></Notice
				>
			{/each}
			{#each singleKindCompetencies as warning (warning.competency_id)}
				<Notice variant="attention"
					><a
						href={`${base}/evidences?from=summary`}
						data-sveltekit-replacestate
						onclick={hapticTap}
					>
						<span class="grow notice-text">
							{competencyName(warning.competency_id)}: todas sus evidencias son {warning.kind ===
							'actuacion'
								? 'actuaciones'
								: 'producciones'}. El CNEB pide evidencia variada: considera una de otro tipo.
							Puedes guardar igual.
						</span>
					</a></Notice
				>
			{/each}
			{#if pendingBy.total > 0}
				<Notice variant="attention">
					<span class="grow notice-text">
						{pendingBy.total === 1
							? '1 propuesta de Mawta sin revisar'
							: `${pendingBy.total} propuestas de Mawta sin revisar`}:
						{#if pendingBy.criteria > 0}<a
								href={`${base}/criteria?from=summary`}
								data-sveltekit-replacestate
								onclick={hapticTap}>{pendingBy.criteria} en criterios</a
							>{/if}{#if pendingBy.criteria > 0 && pendingBy.evidences + pendingBy.sessions > 0},
						{/if}{#if pendingBy.evidences > 0}<a
								href={`${base}/evidences?from=summary`}
								data-sveltekit-replacestate
								onclick={hapticTap}>{pendingBy.evidences} en evidencias</a
							>{/if}{#if pendingBy.evidences > 0 && pendingBy.sessions > 0},
						{/if}{#if pendingBy.sessions > 0}<a
								href={`${base}/sessions?from=summary`}
								data-sveltekit-replacestate
								onclick={hapticTap}>{pendingBy.sessions} en sesiones</a
							>{/if}. Puedes guardar igual.
					</span>
				</Notice>
			{/if}

			<div class="footer-action">
				<Button variant="primary" block disabled={saving} onclick={() => void save()}>
					{planned ? 'Volver a Tu trimestre' : 'Guardar experiencia'}
				</Button>
				<Action
					variant="remove"
					onclick={() => {
						hapticTap();
						confirmingDelete = true;
					}}
				>
					<Icon name="trash" size={14} /> Eliminar experiencia
				</Action>
			</div>
		{:else if loadError}
			<p class="empty">
				No se pudo cargar la experiencia.
				<Button variant="secondary" onclick={load}>Reintentar</Button>
			</p>
		{:else}<LoadingState label="Cargando…" />{/if}
	</div>

	{#if confirmingDelete}
		<ConfirmDialog
			title="¿Eliminar esta experiencia?"
			description="Se eliminan también sus criterios, evidencias y sesiones."
			confirmLabel="Eliminar"
			onconfirm={() => void remove()}
			oncancel={() => (confirmingDelete = false)}
		/>
	{/if}
</div>

<style>
	.title {
		font-size: var(--mw-type-title-size);
		line-height: 1.15;
	}

	.situation {
		margin: var(--mw-space-3) 0 0;
		font-size: var(--mw-type-body-size);
		line-height: 1.5;
		color: var(--mw-ink);
	}

	.situation.muted {
		color: var(--mw-ink-muted);
	}

	.sum-row {
		align-items: baseline;
		gap: var(--mw-space-2);
		padding: 8px 0;
		font-size: var(--mw-type-small-size);
		line-height: 1.4;
		color: var(--mw-ink);
		text-decoration: none;
	}

	.sum-row + .sum-row {
		border-top: 1px solid var(--mw-line);
	}

	.sum-value {
		flex-shrink: 0;
		max-width: 55%;
		text-align: right;
		font-size: var(--mw-type-caption-size);
		color: var(--mw-ink-secondary);
	}

	.notice-text {
		font-size: var(--mw-type-small-size);
		line-height: 1.4;
	}

	.footer-action {
		margin-top: var(--mw-space-6);
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: var(--mw-space-3);
	}

	.empty {
		margin: var(--mw-space-4) 0 0;
		font-size: var(--mw-type-small-size);
		color: var(--mw-ink-muted);
	}
</style>
