<script lang="ts">
	import { onMount } from 'svelte';
	import { loadToday } from '$lib/lesson';
	import { currentSession, entries, entryKey, students } from '$lib/stores';
	import Header from './Header.svelte';
	import RosterRow from './RosterRow.svelte';
	import SetAllBar from './SetAllBar.svelte';
	import Toast from './Toast.svelte';

	let ready = $state(false);
	let searchQuery = $state('');

	const showAssessment = $derived(
		$currentSession?.blocks.some((b) => b.kind === 'assessment') ?? false
	);

	const filteredStudents = $derived.by(() => {
		const query = searchQuery.trim().toLowerCase();
		if (query === '') return $students;
		return $students.filter(
			(s) =>
				s.firstName.toLowerCase().includes(query) ||
				s.lastName.toLowerCase().includes(query)
		);
	});

	const scrollKey = (): string => `lesson-scroll:${$currentSession?.id ?? ''}`;

	onMount(() => {
		let saveTimer: ReturnType<typeof setTimeout> | undefined;
		const saveScroll = (): void => {
			clearTimeout(saveTimer);
			saveTimer = setTimeout(() => {
				if ($currentSession) localStorage.setItem(scrollKey(), String(window.scrollY));
			}, 150);
		};

		void loadToday().then(() => {
			ready = true;
			const saved = localStorage.getItem(scrollKey());
			if (saved) {
				requestAnimationFrame(() => window.scrollTo(0, Number(saved)));
			}
			window.addEventListener('scroll', saveScroll, { passive: true });
		});

		return () => {
			clearTimeout(saveTimer);
			window.removeEventListener('scroll', saveScroll);
		};
	});
</script>

<main class="screen">
	<Header />
	{#if ready && $currentSession}
		<SetAllBar />
		<div class="search-box">
			<input
				type="text"
				placeholder="Search students by name..."
				bind:value={searchQuery}
				class="search-input"
			/>
		</div>
		<div class="roster">
			{#each filteredStudents as student (student.id)}
				{@const entry = $entries.get(entryKey($currentSession.id, student.id))}
				{#if entry}
					<RosterRow {entry} {student} {showAssessment} />
				{/if}
			{/each}
		</div>
	{/if}
</main>

<Toast />

<style>
	.screen {
		max-width: 1200px;
		margin: 0 auto;
		padding: 0 var(--space-lg) var(--space-3xl);
	}

	.search-box {
		margin-top: var(--space-lg);
		margin-bottom: var(--space-lg);
	}

	.search-input {
		width: 100%;
		height: 40px;
		padding: 0 var(--space-md);
		border: 1px solid var(--neutral-300);
		border-radius: var(--radius-md);
		font-size: 14px;
		transition: border-color 100ms ease-out;
	}

	.search-input:focus {
		outline: none;
		border-color: var(--primary);
		box-shadow: 0 0 0 3px rgba(var(--primary-rgb), 0.1);
	}

	.roster {
		display: flex;
		flex-direction: column;
		gap: var(--space-md);
	}

	@media (min-width: 768px) {
		.screen {
			padding: 0 var(--space-xl) var(--space-3xl);
		}
	}
</style>
