<script lang="ts">
	import { onMount } from 'svelte';
	import Icon from '$lib/components/Icon.svelte';
	import LevelBadge from '$lib/components/LevelBadge.svelte';
	import RosterRow from '$lib/components/RosterRow.svelte';
	import TopBar from '$lib/components/TopBar.svelte';
	import { page } from '$app/state';
	import { TIER_LABELS, type Tier } from '$lib/grades';
	import { hapticSuccess } from '$lib/haptics';
	import { anyUnmarked, loadSession, markAllPresent } from '$lib/lesson';
	import { currentCourse, currentSession, entries, entryKey, students } from '$lib/stores';
	import { showToast } from '$lib/toast';

	let ready = $state(false);
	let loadError = $state(false);
	let searchQuery = $state('');

	const courseId = $derived(page.params.courseId ?? '');
	const sessionId = $derived(page.params.sessionId ?? '');

	const filteredStudents = $derived.by(() => {
		const query = searchQuery.trim().toLowerCase();
		if (query === '') return $students;
		return $students.filter(
			(s) =>
				s.firstName.toLowerCase().includes(query) || s.lastName.toLowerCase().includes(query)
		);
	});

	// Section average on the same tier scale as each row, computed server-side.
	const sectionAverage = $derived.by(() => {
		const code = $currentSession?.sectionAverageCode;
		if (code !== 'AD' && code !== 'A' && code !== 'B' && code !== 'C') return null;
		const tier = code as Tier;
		return { tier, label: TIER_LABELS[tier] };
	});

	const markedCount = $derived.by(() => {
		const session = $currentSession;
		if (!session) return 0;
		return $students.filter(
			(s) => $entries.get(entryKey(session.id, s.id))?.attendance !== null
		).length;
	});

	const hasUnmarked = $derived.by(() => {
		// Touch the entries store so this recomputes on every attendance change.
		void $entries;
		return anyUnmarked();
	});

	const topic = $derived($currentSession?.topic ?? '');

	const dateLabel = $derived(
		$currentSession
			? $currentSession.date.toLocaleDateString('es-PE', {
					day: 'numeric',
					month: 'short'
				})
			: ''
	);

	const scrollKey = (): string => `lesson-scroll:${$currentSession?.id ?? ''}`;

	async function handleAllPresent(): Promise<void> {
		hapticSuccess();
		const marked = await markAllPresent();
		if (marked > 0) showToast(`${marked} marcados presentes`);
	}

	async function load(): Promise<void> {
		ready = false;
		loadError = false;
		try {
			await loadSession(sessionId);
			ready = true;
		} catch {
			loadError = true;
		}
	}

	onMount(() => {
		let saveTimer: ReturnType<typeof setTimeout> | undefined;
		const saveScroll = (): void => {
			clearTimeout(saveTimer);
			saveTimer = setTimeout(() => {
				if ($currentSession) localStorage.setItem(scrollKey(), String(window.scrollY));
			}, 150);
		};

		void load().then(() => {
			if (loadError) return;
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

<svelte:head>
	<title>{$currentCourse?.name ?? 'Clase'} — Lección</title>
</svelte:head>

<TopBar back="/class/{courseId}" />

<div class="body">
	<p class="title">{$currentCourse?.name ?? ''}</p>
	<p class="subtitle">
		{#if topic}{topic} · {/if}{dateLabel}
	</p>

	{#if ready && $currentSession}
		{#if sectionAverage}
			<div class="row average">
				<div>
					<p class="average-label">PROMEDIO DE SECCIÓN</p>
					<p class="average-value">{sectionAverage.label}</p>
				</div>
				<LevelBadge tier={sectionAverage.tier} size={32} />
			</div>
		{/if}

		<div class="row attendance-summary">
			<div class="row status">
				<span class="check" class:complete={!hasUnmarked}>
					<Icon name="circle-check" size={16} />
				</span>
				<span>{markedCount}/{$students.length} asistencia registrada</span>
			</div>
			{#if hasUnmarked}
				<button class="pill-light pressable" onclick={handleAllPresent}>Todos presentes</button>
			{/if}
		</div>

		<div class="search-wrap">
			<span class="search-icon"><Icon name="search" size={16} /></span>
			<input class="search" type="text" placeholder="Buscar alumno..." bind:value={searchQuery} />
		</div>

		<div class="roster">
			{#each filteredStudents as student (student.id)}
				{@const entry = $entries.get(entryKey($currentSession.id, student.id))}
				{#if entry}
					<RosterRow {entry} {student} />
				{/if}
			{/each}
		</div>

		{#if filteredStudents.length === 0}
			<p class="empty">Ningún alumno coincide con «{searchQuery}».</p>
		{/if}
	{:else if loadError}
		<p class="empty">
			No se pudo cargar la sesión.
			<button class="pill-light pressable" onclick={load}>Reintentar</button>
		</p>
	{/if}
</div>

<style>
	.title {
		margin: 0;
		font-weight: 500;
		font-size: 20px;
	}

	.subtitle {
		margin: 2px 0 14px;
		font-size: 13px;
		color: var(--text-secondary);
	}

	.average {
		justify-content: space-between;
		background: var(--surface-1);
		border-radius: var(--radius);
		padding: var(--space-md) 14px;
		margin-bottom: 14px;
	}

	.average-label {
		margin: 0 0 2px;
		font-size: 10px;
		letter-spacing: 0.04em;
		color: var(--text-muted);
		font-family: var(--font-mono);
	}

	.average-value {
		margin: 0;
		font-size: 14px;
		font-weight: 500;
	}

	.attendance-summary {
		justify-content: space-between;
		margin-bottom: var(--space-lg);
	}

	.status {
		gap: 6px;
		font-size: 13px;
	}

	.check {
		display: flex;
		color: var(--text-muted);
	}

	.check.complete {
		color: var(--text-success);
	}

	.search-wrap {
		margin-bottom: var(--space-lg);
	}

	.roster {
		display: flex;
		flex-direction: column;
		gap: 10px;
	}

	.empty {
		font-size: 14px;
		color: var(--text-secondary);
	}
</style>
