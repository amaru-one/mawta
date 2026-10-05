<script lang="ts">
	// "Nueva experiencia" — the placeholder of ticket 3. The route exists so
	// "Crear experiencia" lands somewhere; the screen itself (the teacher's
	// idea, the competencies, Mawta's proposal) is built in the next ticket.
	import { onMount } from 'svelte';
	import { page } from '$app/state';
	import { getClassPlan } from '$lib/api/endpoints/planning';
	import type { ClassPlanDto } from '$lib/api/dto';
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
</script>

<svelte:head>
	<title>Nueva experiencia</title>
</svelte:head>

<TopBar back={`/class/${courseId}/plan`} useHistory />

<div class="body">
	{#if ready && plan}
		<h1 class="screen-title">Nueva experiencia</h1>
		<p class="screen-sub">{plan.term.name}</p>
		<p class="note">
			Aquí contarás tu idea y Mawta armará la propuesta. Esta pantalla todavía no está
			construida.
		</p>
	{:else if loadError}
		<p class="empty">
			No se pudo cargar…
			<button class="pill-light pressable" onclick={load}>Reintentar</button>
		</p>
	{/if}
</div>

<style>
	.screen-sub {
		margin: 10px 0 0;
	}

	.note {
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
