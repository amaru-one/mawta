<script lang="ts">
	// The sessions step of a saved experience (ticket 6 builds the real
	// screen). It follows the page pattern: load with retry, TopBar back with
	// history, and the experience's own title from getExperience.
	import { onMount } from 'svelte';
	import { page } from '$app/state';
	import type { ExperienceDto } from '$lib/api/dto';
	import { getExperience } from '$lib/api/endpoints/planning';
	import TopBar from '$lib/components/TopBar.svelte';

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

	onMount(load);
</script>

<svelte:head>
	<title>Sesiones</title>
</svelte:head>

<TopBar back={`/class/${courseId}/plan/${experienceId}/evidences`} useHistory />

<div class="body">
	{#if ready && experience}
		<p class="eyebrow">{experience.title}</p>
		<h1 class="screen-title">Sesiones</h1>
		<p class="placeholder">Aquí repartirás la experiencia en las clases de tu horario.</p>
	{:else if loadError}
		<p class="empty">
			No se pudo cargar…
			<button class="pill-light pressable" onclick={load}>Reintentar</button>
		</p>
	{/if}
</div>

<style>
	.placeholder {
		margin: var(--space-lg) 0 0;
		font-size: 13px;
		line-height: 1.45;
		color: var(--text-muted);
	}

	.empty {
		margin: var(--space-lg) 0 0;
		font-size: 13px;
		color: var(--text-muted);
	}
</style>
