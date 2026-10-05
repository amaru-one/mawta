<script lang="ts">
	import { onMount } from 'svelte';
	import { page } from '$app/state';
	import { list } from '$lib/api/client';
	import type { ClassPlanDto } from '$lib/api/dto';
	import { getClassPlan } from '$lib/api/endpoints/planning';
	import TopBar from '$lib/components/TopBar.svelte';

	const courseId = $derived(page.params.courseId ?? '');

	let ready = $state(false);
	let loadError = $state(false);
	let plan = $state<ClassPlanDto | null>(null);

	async function load(): Promise<void> {
		ready = false;
		loadError = false;
		try {
			plan = await getClassPlan(courseId);
			ready = true;
		} catch {
			loadError = true;
		}
	}

	onMount(load);

	// The plan screen's own read is one request; a failed load only offers the
	// retry, the same as the criteria screen.
	const experiences = $derived(list(plan?.experiences));
	const competencies = $derived(list(plan?.competencies));

	// Status is written as text, never a chip (the prototype's wording).
	const STATUS_LABEL: Record<string, string> = {
		planificada: 'Planificada',
		toca: 'Toca este trimestre',
		puede_esperar: 'Puede esperar',
	};
</script>

<svelte:head>
	<title>Tu trimestre</title>
</svelte:head>

<TopBar back={`/class/${courseId}`} useHistory />

<div class="body">
	{#if ready && plan}
		<h1 class="screen-title">Tu trimestre</h1>
		<p class="screen-sub">
			{plan.term.name} · {plan.term.starts_on} – {plan.term.ends_on} · {plan.class_dates_total}
			clases
		</p>

		{#if experiences.length > 0}
			<p class="eyebrow">Experiencias · {experiences.length}</p>
			<div class="stack">
				{#each experiences as experience (experience.id)}
					<div class="card exp">
						<p class="exp-title">{experience.title}</p>
						<p class="meta">
							{experience.starts_on} – {experience.ends_on} · {experience.class_dates} clases
						</p>
						<p class="exp-comps">
							{list(experience.competencies)
								.map((competency) => competency.name)
								.join(' · ')}
						</p>
					</div>
				{/each}
			</div>
		{:else}
			<div class="card empty-card">
				<p class="empty-title">Aún no hay experiencias en este trimestre</p>
				<p class="empty-text">
					Cuéntale a Mawta tu idea: detecta las competencias y arma la propuesta con criterios,
					evidencias y sesiones.
				</p>
			</div>
		{/if}

		<p class="eyebrow comps-label">Competencias este trimestre</p>
		<div class="context-card">
			{#each competencies as competency (competency.id)}
				<div class="comp-row">
					<p class="comp-name">{competency.name}</p>
					<p class="comp-status">{STATUS_LABEL[competency.status] ?? competency.status}</p>
					<p class="comp-detail">
						{competency.capabilities_covered_this_term} de {competency.capabilities_total}
						capacidades con criterio
					</p>
				</div>
			{/each}
		</div>
	{:else if loadError}
		<p class="empty">
			No se pudo cargar el plan.
			<button class="pill-light pressable" onclick={load}>Reintentar</button>
		</p>
	{/if}
</div>

<style>
	.screen-sub {
		margin-bottom: var(--space-lg);
	}

	.eyebrow {
		margin-bottom: var(--space-sm);
	}

	.comps-label {
		margin-top: var(--space-xl);
	}

	.exp {
		padding: var(--space-md);
	}

	.exp-title {
		margin: 0;
		font-size: 15px;
		font-weight: 700;
		letter-spacing: -0.01em;
	}

	.exp-comps {
		margin: 6px 0 0;
		font-size: 12px;
		color: var(--text-muted);
	}

	.empty-card {
		padding: var(--space-lg);
	}

	.empty-title {
		margin: 0;
		font-size: 15px;
		font-weight: 700;
	}

	.empty-text {
		margin: 6px 0 0;
		font-size: 13px;
		color: var(--text-muted);
	}

	.comp-row {
		padding: var(--space-sm) 0;
	}

	.comp-row + .comp-row {
		border-top: 0.5px solid var(--hair);
	}

	.comp-name {
		margin: 0;
		font-size: 13px;
		font-weight: 700;
	}

	/* Status is written as text, never a chip. */
	.comp-status {
		margin: 2px 0 0;
		font-size: 12px;
		color: var(--text-secondary);
	}

	.comp-detail {
		margin: 2px 0 0;
		font-size: 12px;
		color: var(--text-muted);
	}

	.empty {
		margin: var(--space-lg) 0 0;
		font-size: 13px;
		color: var(--text-muted);
	}
</style>
