<script lang="ts">
	import CourseCard from '$lib/components/CourseCard.svelte';
	import Icon from '$lib/components/Icon.svelte';
	import TopBar from '$lib/components/TopBar.svelte';
	import { HOME_COURSES } from '$lib/mocks';

	let query = $state('');

	const matches = $derived.by(() => {
		const q = query.trim().toLowerCase();
		if (q === '') return HOME_COURSES;
		return HOME_COURSES.filter((c) => c.name.toLowerCase().includes(q));
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

	{#if matches.length === 0}
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
</style>
