<script lang="ts">
	import { onMount } from 'svelte';
	import { page } from '$app/state';
	import { getSiagieReport } from '$lib/api/endpoints/competencies';
	import { toSiagieReport } from '$lib/api/mappers';
	import Icon from '$lib/components/Icon.svelte';
	import LevelBadge from '$lib/components/LevelBadge.svelte';
	import TopBar from '$lib/components/TopBar.svelte';
	import { hapticTap } from '$lib/haptics';
	import type { Tier } from '$lib/grades';
	import type { SiagieReport } from '$lib/types';

	const courseId = $derived(page.params.courseId ?? '');

	let ready = $state(false);
	let loadError = $state(false);
	let report = $state<SiagieReport | null>(null);

	async function load(): Promise<void> {
		ready = false;
		loadError = false;
		try {
			report = toSiagieReport(await getSiagieReport(courseId));
			ready = true;
		} catch {
			loadError = true;
		}
	}

	onMount(load);

	let expandedStudents = $state<Set<string>>(new Set());

	function toggleStudent(studentId: string): void {
		hapticTap();
		const next = new Set(expandedStudents);
		if (next.has(studentId)) {
			next.delete(studentId);
		} else {
			next.add(studentId);
		}
		expandedStudents = next;
	}

	function completedCount(student: SiagieReport['students'][number]): number {
		return student.competencies.filter((c) => c.level !== null).length;
	}

	function isTier(level: Tier | null): level is Tier {
		return level !== null;
	}
</script>

<svelte:head>
	<title>Reporte SIAGIE</title>
</svelte:head>

<!-- Single entry point (the class dashboard), so the back arrow is hardcoded
     rather than using useHistory — see routes/SPEC.md's convention. -->
<TopBar back="/class/{courseId}" />

<div class="body">
	{#if ready && report}
		<p class="title">Reporte de fin de periodo</p>
		<p class="subtitle">{report.className} · {report.termName}</p>

		<p class="notice">{report.notice}</p>

		{#if !report.ready}
			<div class="banner">
				<Icon name="alert" size={16} />
				<div class="grow">
					<p class="banner-title">
						{report.blocking.length}
						{report.blocking.length === 1
							? 'conclusión descriptiva faltante'
							: 'conclusiones descriptivas faltantes'}
					</p>
					{#each report.blocking as b (b.studentId + b.competencyId)}
						<p class="banner-item">{b.studentName} — {b.competency}</p>
					{/each}
				</div>
			</div>
		{/if}

		<p class="eyebrow">ALUMNOS</p>

		<div class="stack">
			{#each report.students as student (student.studentId)}
				{@const expanded = expandedStudents.has(student.studentId)}
				{@const total = student.competencies.length}
				{@const done = completedCount(student)}
				<div class="card student" class:expanded>
					<button
						type="button"
						class="student-header pressable"
						onclick={() => toggleStudent(student.studentId)}
						aria-expanded={expanded}
					>
						<div class="grow">
							<p class="student-name">{student.studentName}</p>
							<p class="student-progress" class:incomplete={done < total}>
								{done}/{total} competencias completas
							</p>
						</div>
						<span class="chevron" class:open={expanded}>
							<Icon name="chevron-right" size={16} />
						</span>
					</button>

					{#if expanded}
						<div class="student-body">
							{#each student.competencies as comp, i (comp.competencyId)}
								{#if i > 0}<div class="divider"></div>{/if}
								<div class="row comp-row">
									<p class="comp-name grow">{comp.name}</p>
									{#if isTier(comp.level)}
										<LevelBadge tier={comp.level} size={24} />
									{:else}
										<span class="dash">—</span>
									{/if}
								</div>
							{/each}
						</div>
					{/if}
				</div>
			{/each}
		</div>

		{#if report.students.length === 0}
			<p class="empty">Aún no hay alumnos en esta clase.</p>
		{/if}
	{:else if loadError}
		<p class="empty">No se pudo cargar el reporte — revisa tu conexión.</p>
	{/if}
</div>

<style>
	.body {
		padding: var(--space-lg);
	}

	.title {
		margin: 0;
		font-weight: 500;
		font-size: 20px;
	}

	.subtitle {
		margin: 2px 0 var(--space-lg);
		font-size: 13px;
		color: var(--text-secondary);
	}

	.notice {
		margin: 0 0 var(--space-lg);
		font-size: 12px;
		color: var(--text-muted);
		line-height: 1.4;
	}

	.banner {
		display: flex;
		align-items: flex-start;
		gap: 10px;
		background: var(--bg-danger);
		border-radius: var(--radius);
		padding: var(--space-md) 14px;
		margin-bottom: var(--space-lg);
		color: var(--text-danger);
	}

	.grow {
		flex: 1;
		min-width: 0;
	}

	.banner-title {
		margin: 0 0 4px;
		font-size: 13px;
		font-weight: 500;
	}

	.banner-item {
		margin: 2px 0 0;
		font-size: 12px;
		color: var(--text-secondary);
	}

	.eyebrow {
		margin: 0 0 10px;
		font-size: 12px;
		font-weight: 500;
		letter-spacing: 0.04em;
		color: var(--text-muted);
	}

	.stack {
		display: flex;
		flex-direction: column;
		gap: var(--space-sm);
	}

	.student {
		padding: 0;
		overflow: hidden;
	}

	.student-header {
		display: flex;
		align-items: flex-start;
		gap: 10px;
		width: 100%;
		padding: var(--space-md) 14px;
		background: transparent;
		border: none;
		text-align: left;
		color: inherit;
		font: inherit;
		cursor: pointer;
	}

	.student-name {
		margin: 0;
		font-size: 14px;
		font-weight: 500;
	}

	.student-progress {
		margin: 2px 0 0;
		font-size: 11px;
		color: var(--text-secondary);
	}

	.student-progress.incomplete {
		color: var(--text-danger);
	}

	.chevron {
		display: inline-flex;
		flex-shrink: 0;
		color: var(--text-muted);
		transition: transform 150ms;
	}

	.chevron.open {
		transform: rotate(90deg);
	}

	.student-body {
		padding: 0 14px var(--space-md);
	}

	.comp-row {
		align-items: flex-start;
		gap: 10px;
		padding: var(--space-sm) 0;
	}

	.comp-name {
		margin: 0;
		font-size: 13px;
	}

	.dash {
		font-size: 12px;
		color: var(--text-muted);
		flex-shrink: 0;
	}

	.divider {
		border-top: 0.5px solid var(--border);
	}

	.empty {
		margin: var(--space-xl) 0;
		text-align: center;
		font-size: 13px;
		color: var(--text-muted);
	}
</style>
