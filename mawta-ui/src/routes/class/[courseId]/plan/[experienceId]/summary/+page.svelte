<script lang="ts">
	// "Revisar y guardar": a compact summary of the experience and its notes.
	// Notes never block: a capacidad without a criterio or proposals still to
	// review are said, each linking to its step, and the teacher can save
	// anyway. A planned experience opens here from "Tu trimestre"; every step is
	// reachable from it, and it can be deleted.
	import { onMount } from 'svelte';
	import { page } from '$app/state';
	import { goto } from '$app/navigation';
	import { list } from '$lib/api/client';
	import type { CurriculumDto, ExperienceDto, WarningDto } from '$lib/api/dto';
	import {
		confirmExperience,
		deleteExperience,
		getClassCurriculum,
		getExperience,
	} from '$lib/api/endpoints/planning';
	import ConfirmDialog from '$lib/components/ConfirmDialog.svelte';
	import Icon from '$lib/components/Icon.svelte';
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

	function coveredOf(competencyId: string): number {
		const covered = new Set(
			criteria
				.filter((criterion) => criterion.competency_id === competencyId)
				.flatMap((criterion) => list(criterion.capability_ids))
		);
		return capabilitiesOf(competencyId).filter((capability) => covered.has(capability.id)).length;
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

	const pendingCount = $derived(
		warnings.reduce(
			(sum, warning) => (warning.code === 'pending_proposals' ? sum + warning.count : sum),
			0
		)
	);

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
			void goto(`/class/${courseId}/plan`);
			return;
		}
		if (saving) return;
		saving = true;
		try {
			await confirmExperience(experienceId);
			showToast('Experiencia guardada');
			void goto(`/class/${courseId}/plan`);
		} catch {
			showToast('No se pudo guardar la experiencia');
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
			void goto(`/class/${courseId}/plan`);
		} catch {
			showToast('No se pudo eliminar la experiencia');
		}
	}
</script>

<svelte:head>
	<title>Revisar y guardar</title>
</svelte:head>

<TopBar back={`/class/${courseId}/plan`} useHistory />

<div class="body">
	{#if ready && experience}
		<p class="eyebrow">{planned ? 'Experiencia planificada' : 'Revisar y guardar'}</p>
		<h1 class="screen-title title">{experience.title}</h1>
		<p class="screen-sub">
			{fmtDate(experience.starts_on)} – {fmtDate(experience.ends_on)} · {dates.length} clases
		</p>

		<p class="situation">{experience.situation_text}</p>

		<div class="context-card summary">
			{#each comps as competency (competency.id)}
				<a class="sum-row row pressable" href={`${base}/criteria`} onclick={hapticTap}>
					<span class="grow">{competency.name}</span>
					<span class="sum-value">
						{coveredOf(competency.id)} de {capabilitiesOf(competency.id).length} capacidades con criterio
					</span>
				</a>
			{/each}
			<a class="sum-row row pressable" href={`${base}/criteria`} onclick={hapticTap}>
				<span class="grow">Criterios</span>
				<span class="sum-value">{criteria.length}</span>
			</a>
			<a class="sum-row row pressable" href={`${base}/evidences`} onclick={hapticTap}>
				<span class="grow">Evidencias</span>
				<span class="sum-value">{evidences.length} · {placed} ubicadas en sesiones</span>
			</a>
			<a class="sum-row row pressable" href={`${base}/sessions`} onclick={hapticTap}>
				<span class="grow">Sesiones</span>
				<span class="sum-value">{sessions.length} de {dates.length} fechas</span>
			</a>
		</div>

		{#if missingCapabilities.length > 0}
			<a class="notice pressable" href={`${base}/criteria`} onclick={hapticTap}>
				<Icon name="alert" size={16} />
				<span class="grow notice-text">
					{missingCapabilities.length === 1
						? '1 capacidad sin criterio'
						: `${missingCapabilities.length} capacidades sin criterio`}: {missingCapabilities.join(
						', '
					)}. Puedes guardar igual: es un aviso, no un bloqueo.
				</span>
			</a>
		{/if}
		{#if pendingCount > 0}
			<a class="notice pressable" href={`${base}/criteria`} onclick={hapticTap}>
				<Icon name="sparkles" size={16} />
				<span class="grow notice-text">
					{pendingCount === 1
						? '1 propuesta sin revisar'
						: `${pendingCount} propuestas sin revisar`}
					de Mawta. Puedes guardar igual.
				</span>
			</a>
		{/if}

		<div class="footer-action">
			<button class="btn-block btn-primary pressable" disabled={saving} onclick={() => void save()}>
				{planned ? 'Volver a Tu trimestre' : 'Guardar experiencia'}
			</button>
			<button
				class="delete pressable"
				onclick={() => {
					hapticTap();
					confirmingDelete = true;
				}}
			>
				<Icon name="trash" size={14} /> Eliminar experiencia
			</button>
		</div>
	{:else if loadError}
		<p class="empty">
			No se pudo cargar la experiencia.
			<button class="pill-light pressable" onclick={load}>Reintentar</button>
		</p>
	{/if}
</div>

{#if confirmingDelete}
	<ConfirmDialog
		title="¿Eliminar esta experiencia?"
		text="Se eliminan también sus criterios, evidencias y sesiones."
		confirmLabel="Eliminar"
		onconfirm={() => void remove()}
		oncancel={() => (confirmingDelete = false)}
	/>
{/if}

<style>
	.title {
		font-size: 28px;
		line-height: 1.15;
	}

	.situation {
		margin: var(--space-md) 0 0;
		font-size: 14px;
		line-height: 1.5;
		color: var(--text-primary);
	}

	.summary {
		margin-top: var(--space-md);
	}

	.sum-row {
		align-items: baseline;
		gap: var(--space-sm);
		padding: 8px 0;
		font-size: 13px;
		line-height: 1.4;
		color: var(--text-primary);
		text-decoration: none;
	}

	.sum-row + .sum-row {
		border-top: 0.5px solid var(--hair);
	}

	.sum-value {
		flex-shrink: 0;
		max-width: 55%;
		text-align: right;
		font-size: 12px;
		color: var(--text-secondary);
	}

	.notice {
		display: flex;
		align-items: flex-start;
		gap: var(--space-sm);
		background: var(--bg-danger);
		border-radius: var(--radius);
		padding: var(--space-sm) var(--space-md);
		margin-top: var(--space-md);
		color: var(--text-primary);
		text-decoration: none;
	}

	.notice-text {
		font-size: 13px;
		line-height: 1.4;
	}

	.footer-action {
		margin-top: var(--space-xl);
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: var(--space-md);
	}

	.footer-action .btn-primary:disabled {
		opacity: 0.6;
	}

	.delete {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		padding: 8px 12px;
		background: none;
		font-size: 13px;
		font-weight: 600;
		color: var(--text-muted);
	}

	.empty {
		margin: var(--space-lg) 0 0;
		font-size: 13px;
		color: var(--text-muted);
	}
</style>
