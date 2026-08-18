<script lang="ts">
	import { onMount } from 'svelte';
	import Icon from '$lib/components/Icon.svelte';
	import LevelBadge from '$lib/components/LevelBadge.svelte';
	import RosterRow from '$lib/components/RosterRow.svelte';
	import TopBar from '$lib/components/TopBar.svelte';
	import { page } from '$app/state';
	import { gradeFor, loadScoresForStudents, tierFor, TIER_LABELS } from '$lib/grades';
	import { hapticSuccess } from '$lib/haptics';
	import { areAllPresent, loadToday, setAllPresent } from '$lib/lesson';
	import {
		assessments,
		currentCourse,
		currentSession,
		entries,
		entryKey,
		scores,
		students
	} from '$lib/stores';
	import { showToast } from '$lib/toast';

	let ready = $state(false);
	let searchQuery = $state('');

	const courseId = $derived(page.params.courseId ?? '');

	const filteredStudents = $derived.by(() => {
		const query = searchQuery.trim().toLowerCase();
		if (query === '') return $students;
		return $students.filter(
			(s) =>
				s.firstName.toLowerCase().includes(query) || s.lastName.toLowerCase().includes(query)
		);
	});

	// Section average across the whole roster, on the same tier scale as each row.
	const sectionAverage = $derived.by(() => {
		if ($students.length === 0) return null;
		const total = $students.reduce(
			(sum, s) => sum + gradeFor(s.id, $scores, $assessments).percent,
			0
		);
		const tier = tierFor(Math.round(total / $students.length));
		return { tier, label: TIER_LABELS[tier] };
	});

	const presentCount = $derived.by(() => {
		const session = $currentSession;
		if (!session) return 0;
		return $students.filter(
			(s) => $entries.get(entryKey(session.id, s.id))?.attendance === 'present'
		).length;
	});

	const allPresent = $derived.by(() => {
		// Touch the entries store so this recomputes on every attendance change.
		void $entries;
		return areAllPresent();
	});

	const topic = $derived($currentSession?.blocks.find((b) => b.kind === 'lesson')?.topic ?? '');

	const dateLabel = $derived(
		$currentSession
			? new Date($currentSession.date).toLocaleDateString('es-PE', {
					day: 'numeric',
					month: 'short'
				})
			: ''
	);

	const scrollKey = (): string => `lesson-scroll:${$currentSession?.id ?? ''}`;

	function toggleAllPresent(): void {
		const wasAllPresent = allPresent;
		const undo = setAllPresent();
		hapticSuccess();
		showToast(wasAllPresent ? 'Se quitó la asistencia' : 'Todos marcados presentes', {
			onUndo: () => {
				undo.restore();
				showToast('Cambio deshecho');
			}
		});
	}

	onMount(() => {
		let saveTimer: ReturnType<typeof setTimeout> | undefined;
		const saveScroll = (): void => {
			clearTimeout(saveTimer);
			saveTimer = setTimeout(() => {
				if ($currentSession) localStorage.setItem(scrollKey(), String(window.scrollY));
			}, 150);
		};

		void loadToday()
			.then(() => loadScoresForStudents($students.map((s) => s.id)))
			.then(() => {
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
				<span class="check" class:complete={allPresent}>
					<Icon name="circle-check" size={16} />
				</span>
				<span>{presentCount}/{$students.length} asistencia registrada</span>
			</div>
			<button class="pill-light pressable" onclick={toggleAllPresent}>
				{allPresent ? 'Quitar todos' : 'Todos presentes'}
			</button>
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
