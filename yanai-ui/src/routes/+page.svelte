<script lang="ts">
	import { onMount } from 'svelte';
	import { getHome } from '$lib/api/endpoints/home';
	import { toHomeCourses } from '$lib/api/mappers';
	import CourseCard from '$lib/components/CourseCard.svelte';
	import Icon from '$lib/components/Icon.svelte';
	import TopBar from '$lib/components/TopBar.svelte';
	import type { HomeCourse } from '$lib/types';

	let query = $state('');
	let courses = $state<HomeCourse[]>([]);
	let loading = $state(true);
	let loadError = $state(false);

	async function load() {
		loading = true;
		loadError = false;
		try {
			courses = toHomeCourses(await getHome());
		} catch {
			loadError = true;
		} finally {
			loading = false;
		}
	}

	onMount(load);

	// The home payload already lists every class, so search filters locally.
	const matches = $derived.by(() => {
		const q = query.trim().toLowerCase();
		if (q === '') return courses;
		return courses.filter((c) => c.name.toLowerCase().includes(q));
	});

	const today = $derived(matches.filter((c) => c.bucket === 'today'));
	const week = $derived(matches.filter((c) => c.bucket === 'week'));
</script>

<svelte:head>
	<title>Yanai — Inicio</title>
</svelte:head>

<TopBar variant="home" />

<div class="body">
	<div class="search-wrap">
		<span class="search-icon"><Icon name="search" size={16} /></span>
		<input class="search" type="text" placeholder="Buscar por clase" bind:value={query} />
	</div>

	{#if today.length > 0}
		<p class="eyebrow">HOY</p>
		<div class="stack">
			{#each today as course (course.id)}
				<CourseCard {course} />
			{/each}
		</div>
	{/if}

	{#if week.length > 0}
		<p class="eyebrow">ESTA SEMANA</p>
		<div class="stack">
			{#each week as course (course.id)}
				<CourseCard {course} />
			{/each}
		</div>
	{/if}

	{#if loadError}
		<p class="empty">
			No se pudieron cargar las clases.
			<button class="retry pressable" onclick={load}>Reintentar</button>
		</p>
	{:else if !loading && matches.length === 0}
		<p class="empty">No hay clases que coincidan con «{query}».</p>
	{/if}
</div>

<style>
	.search-wrap {
		margin-bottom: 20px;
	}

	.stack {
		display: flex;
		flex-direction: column;
		gap: var(--space-md);
		margin-bottom: 20px;
	}

	.empty {
		font-size: 14px;
		color: var(--text-secondary);
	}

	.retry {
		margin-left: var(--space-sm);
		border: 1px solid var(--border);
		border-radius: var(--radius-md);
		background: var(--surface-1);
		padding: 4px 10px;
		font-size: 13px;
		color: inherit;
	}
</style>
