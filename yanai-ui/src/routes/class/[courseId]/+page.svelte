<script lang="ts">
	import { onMount } from 'svelte';
	import { page } from '$app/state';
	import { getClassDashboard } from '$lib/api/endpoints/classes';
	import Icon from '$lib/components/Icon.svelte';
	import TopBar from '$lib/components/TopBar.svelte';
	import type { Tier } from '$lib/grades';
	import { hapticTap } from '$lib/haptics';
	import { CLASS_DASHBOARD } from '$lib/mocks';

	const courseId = $derived(page.params.courseId ?? '');

	// Real class identity + today's session come from the API; the analytics
	// below still render the sample dashboard until that screen is wired up.
	let name = $state(CLASS_DASHBOARD.name);
	let sessionId = $state<string | null>(null);

	onMount(async () => {
		try {
			const dash = await getClassDashboard(courseId);
			name = dash.name;
			sessionId = dash.next_session?.session_id ?? null;
		} catch {
			// keep the sample header; the start button stays hidden
		}
	});

	const d = CLASS_DASHBOARD;

	const TIER_FILL: Record<Tier, string> = {
		AD: 'var(--fill-accent)',
		A: 'var(--fill-success)',
		B: 'var(--fill-warning)',
		C: 'var(--fill-tier-c)'
	};
</script>

<svelte:head>
	<title>{name} — Panel</title>
</svelte:head>

<TopBar back="/" />

<div class="body">
	<p class="title">{name}</p>
	<p class="subtitle">{d.summary}</p>

	<div class="today">
		<p class="today-label">{d.todayLabel}</p>
		<p class="today-time">{d.todayTime}</p>
		<p class="today-topic">{d.todayTopic}</p>
		{#if sessionId !== null}
			<a class="start pressable" href="/class/{courseId}/lesson/{sessionId}" onclick={hapticTap}>
				Iniciar clase →
			</a>
		{/if}
	</div>

	<div class="grid3 stats">
		<div class="stat"><p>Notas reg.</p><p>{d.stats.gradesEntered}</p></div>
		<div class="stat"><p>Asistencia</p><p>{d.stats.attendance}</p></div>
		<div class="stat"><p>En riesgo</p><p>{d.stats.atRisk}</p></div>
	</div>

	<div class="card section">
		<p class="section-title">Distribución de logros</p>
		<div class="bar">
			{#each d.distribution as slice (slice.tier)}
				<div style="flex:{slice.count};background:{TIER_FILL[slice.tier]}"></div>
			{/each}
		</div>
		<div class="legend">
			{#each d.distribution as slice (slice.tier)}
				<div class="row legend-item">
					<span
						class="legend-dot"
						class:outlined={slice.tier === 'C'}
						style="background:{TIER_FILL[slice.tier]}"
					></span>
					<span>{slice.tier} · {slice.count}</span>
				</div>
			{/each}
		</div>
	</div>

	<div class="card section">
		<p class="section-title">Alumnos en riesgo</p>
		{#each d.risk as student, i (student.name)}
			{#if i > 0}<div class="divider"></div>{/if}
			<div class="row list-row">
				<span class="bullet"></span>
				<div class="grow">
					<p class="list-title">{student.name}</p>
					<p class="list-detail danger">{student.reason}</p>
				</div>
				<span class="chevron"><Icon name="chevron-right" size={16} /></span>
			</div>
		{/each}
	</div>

	<div class="card section">
		<p class="section-title">Pendientes</p>
		{#each d.pending as item, i (item.title)}
			{#if i > 0}<div class="divider"></div>{/if}
			<div class="row list-row">
				<span class="pending-icon"><Icon name={item.icon} size={16} /></span>
				<div class="grow">
					<p class="list-title">{item.title}</p>
					<p class="list-detail">{item.detail}</p>
				</div>
				<span class="chevron"><Icon name="chevron-right" size={16} /></span>
			</div>
		{/each}
	</div>

	<p class="eyebrow">PRÓXIMAS CLASES</p>
	<div class="stack">
		{#each d.upcoming as s (s.title)}
			<div class="card row session">
				<div class="date">
					<p class="day">{s.day}</p>
					<p class="month">{s.month}</p>
				</div>
				<div class="grow">
					<p class="list-title">{s.title}</p>
					<p class="list-detail">{s.detail}</p>
				</div>
				<span class="chevron"><Icon name="chevron-right" size={16} /></span>
			</div>
		{/each}
	</div>

	<p class="eyebrow">CLASES ANTERIORES</p>
	<div class="stack">
		{#each d.previous as s (s.title)}
			<div class="card row session">
				<div class="date">
					<p class="day">{s.day}</p>
					<p class="month">{s.month}</p>
				</div>
				<div class="grow">
					<p class="list-title tight">{s.title}</p>
					<div class="chips">
						{#each s.chips ?? [] as chip (chip.text)}
							<span class="chip" class:chip-ok={chip.tone === 'ok'} class:chip-bad={chip.tone === 'bad'}>
								{chip.text}
							</span>
						{/each}
					</div>
				</div>
				<span class="chevron"><Icon name="chevron-right" size={16} /></span>
			</div>
		{/each}
	</div>
</div>

<style>
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

	.today {
		background: var(--text-primary);
		border-radius: var(--radius-lg);
		padding: var(--space-lg);
		margin-bottom: 20px;
	}

	.today-label {
		margin: 0 0 var(--space-sm);
		font-size: 11px;
		letter-spacing: 0.05em;
		color: var(--surface-1);
		font-family: var(--font-mono);
	}

	.today-time {
		margin: 0;
		font-weight: 500;
		font-size: 18px;
		color: var(--surface-2);
	}

	.today-topic {
		margin: 2px 0 var(--space-lg);
		font-size: 13px;
		color: var(--surface-1);
	}

	.start {
		display: block;
		width: 100%;
		background: var(--surface-2);
		color: var(--text-primary);
		padding: var(--space-md);
		border-radius: var(--radius);
		font-size: 14px;
		font-weight: 500;
		text-align: center;
		text-decoration: none;
	}

	.stats {
		margin-bottom: var(--space-md);
	}

	.stat p:first-child {
		margin: 0 0 var(--space-xs);
		font-size: 11px;
		color: var(--text-secondary);
	}

	.stat p:last-child {
		margin: 0;
		font-size: 18px;
		font-weight: 500;
	}

	.section {
		padding: 14px var(--space-lg);
		margin-bottom: var(--space-lg);
	}

	.section-title {
		margin: 0 0 10px;
		font-size: 13px;
		font-weight: 500;
	}

	.bar {
		display: flex;
		width: 100%;
		height: 10px;
		border-radius: 6px;
		overflow: hidden;
	}

	.legend {
		display: flex;
		justify-content: space-between;
		margin-top: 10px;
	}

	.legend-item {
		gap: 5px;
		font-size: 11px;
		color: var(--text-secondary);
	}

	.legend-dot {
		width: 8px;
		height: 8px;
		border-radius: 50%;
	}

	.legend-dot.outlined {
		border: 1px solid var(--border-strong);
	}

	.list-row {
		gap: 10px;
		padding: var(--space-sm) 0;
	}

	.grow {
		flex: 1;
		min-width: 0;
	}

	.bullet {
		width: 8px;
		height: 8px;
		border-radius: 50%;
		background: var(--fill-danger);
		flex-shrink: 0;
	}

	.pending-icon {
		color: var(--text-warning);
		display: flex;
		flex-shrink: 0;
	}

	.list-title {
		margin: 0;
		font-size: 14px;
	}

	.list-title.tight {
		margin-bottom: var(--space-xs);
	}

	.list-detail {
		margin: 0;
		font-size: 12px;
		color: var(--text-secondary);
	}

	.list-detail.danger {
		color: var(--text-danger);
	}

	.chevron {
		color: var(--text-muted);
		display: flex;
		flex-shrink: 0;
	}

	.stack {
		display: flex;
		flex-direction: column;
		gap: 10px;
		margin-bottom: 20px;
	}

	.session {
		padding: var(--space-md) var(--space-lg);
	}

	.date {
		text-align: center;
		min-width: 34px;
	}

	.day {
		margin: 0;
		font-size: 15px;
		font-weight: 500;
	}

	.month {
		margin: 0;
		font-size: 10px;
		color: var(--text-muted);
	}

	.chips {
		display: flex;
		gap: 6px;
		flex-wrap: wrap;
	}
</style>
