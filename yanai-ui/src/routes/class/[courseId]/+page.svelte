<script lang="ts">
	import { onMount } from 'svelte';
	import { page } from '$app/state';
	import { list } from '$lib/api/client';
	import type { ClassDashboardDto, SessionSummaryDto } from '$lib/api/dto';
	import { getClassDashboard } from '$lib/api/endpoints/classes';
	import { formatTimeHHMM, parseDateOnly } from '$lib/api/mappers';
	import Icon from '$lib/components/Icon.svelte';
	import TopBar from '$lib/components/TopBar.svelte';
	import { hapticTap } from '$lib/haptics';

	const courseId = $derived(page.params.courseId ?? '');

	let ready = $state(false);
	let loadError = $state(false);
	let d = $state<ClassDashboardDto | null>(null);

	async function load(): Promise<void> {
		ready = false;
		loadError = false;
		try {
			d = await getClassDashboard(courseId);
			ready = true;
		} catch {
			loadError = true;
		}
	}

	onMount(load);

	const TIER_FILL: Record<string, string> = {
		AD: 'var(--fill-accent)',
		A: 'var(--fill-success)',
		B: 'var(--fill-warning)',
		C: 'var(--fill-tier-c)'
	};

	const STATUS_LABEL: Record<string, string> = {
		scheduled: 'SIN INICIAR',
		in_progress: 'EN CURSO',
		completed: 'FINALIZADA'
	};

	const timeRange = (s: SessionSummaryDto): string =>
		`${formatTimeHHMM(s.scheduled_start_at)} – ${formatTimeHHMM(s.scheduled_end_at)}`;

	const dateParts = (s: SessionSummaryDto): { day: string; month: string } => {
		const date = parseDateOnly(s.session_date);
		return {
			day: String(date.getDate()),
			month: date.toLocaleDateString('es-PE', { month: 'short' }).replace('.', '').toUpperCase()
		};
	};

	const asistenciaLabel = $derived(
		d?.stats.asistencia_pct != null ? `${Math.round(d.stats.asistencia_pct * 100)}%` : '—'
	);

	type PendingRow = { icon: 'checklist' | 'clipboard-check'; title: string; detail: string };
	const pending = $derived.by((): PendingRow[] => {
		if (!d) return [];
		const rows: PendingRow[] = list(d.grades_pending).map((g) => ({
			icon: 'checklist' as const,
			title: 'Notas pendientes',
			detail: `${g.title} · ${g.missing} ${g.missing === 1 ? 'alumno' : 'alumnos'}`
		}));
		for (const au of list(d.attendance_unmarked)) {
			rows.push({
				icon: 'clipboard-check',
				title: 'Asistencia sin marcar',
				detail: parseDateOnly(au.session_date).toLocaleDateString('es-PE', {
					day: 'numeric',
					month: 'long'
				})
			});
		}
		return rows;
	});

	const pastChips = (s: SessionSummaryDto): Array<{ text: string; tone: 'ok' | 'bad' }> => {
		const chips: Array<{ text: string; tone: 'ok' | 'bad' }> = [];
		if (s.present_count != null && s.roster_count != null) {
			chips.push({ text: `${s.present_count}/${s.roster_count} presente`, tone: 'ok' });
		}
		if (s.missing_grades != null && s.missing_grades > 0) {
			chips.push({ text: `${s.missing_grades} pendientes`, tone: 'bad' });
		}
		return chips;
	};
</script>

<svelte:head>
	<title>{d?.name ?? 'Clase'} — Panel</title>
</svelte:head>

<TopBar back="/" />

<div class="body">
	{#if ready && d}
		<p class="title">{d.name}</p>
		<p class="subtitle">{d.roster_count} alumnos · {d.sessions_per_week} sesiones/semana</p>

		{#if d.next_session}
			<div class="today">
				<p class="today-label">HOY · {STATUS_LABEL[d.next_session.status] ?? ''}</p>
				<p class="today-time">{timeRange(d.next_session)}</p>
				<p class="today-topic">
					{d.next_session.topic ? `Lección: ${d.next_session.topic}` : 'Sin tema asignado'}
				</p>
				<a
					class="start pressable"
					href="/class/{courseId}/lesson/{d.next_session.session_id}"
					onclick={hapticTap}
				>
					Iniciar clase →
				</a>
			</div>
		{/if}

		<div class="grid3 stats">
			<div class="stat"><p>Notas reg.</p><p>{d.stats.scored}/{d.stats.expected}</p></div>
			<div class="stat"><p>Asistencia</p><p>{asistenciaLabel}</p></div>
			<div class="stat"><p>En riesgo</p><p>{d.stats.en_riesgo}</p></div>
		</div>

		{#if list(d.distribution).length > 0}
			<div class="card section">
				<p class="section-title">Distribución de logros</p>
				<div class="bar">
					{#each list(d.distribution) as slice (slice.code)}
						<div style="flex:{slice.count};background:{TIER_FILL[slice.code] ?? 'var(--border)'}"></div>
					{/each}
				</div>
				<div class="legend">
					{#each list(d.distribution) as slice (slice.code)}
						<div class="row legend-item">
							<span
								class="legend-dot"
								class:outlined={slice.code === 'C'}
								style="background:{TIER_FILL[slice.code] ?? 'var(--border)'}"
							></span>
							<span>{slice.code} · {slice.count}</span>
						</div>
					{/each}
				</div>
			</div>
		{/if}

		{#if list(d.at_risk).length > 0}
			<div class="card section">
				<p class="section-title">Alumnos en riesgo</p>
				{#each list(d.at_risk) as student, i (student.student_id)}
					{#if i > 0}<div class="divider"></div>{/if}
					<a
						class="row list-row risk-link"
						href="/grades/{student.student_id}?class={courseId}&name={encodeURIComponent(
							student.name
						)}&course={encodeURIComponent(d.name)}"
						onclick={hapticTap}
					>
						<span class="bullet"></span>
						<div class="grow">
							<p class="list-title">{student.name}</p>
							<p class="list-detail danger">{student.reason_text}</p>
						</div>
						<span class="chevron"><Icon name="chevron-right" size={16} /></span>
					</a>
				{/each}
			</div>
		{/if}

		{#if pending.length > 0}
			<div class="card section">
				<p class="section-title">Pendientes</p>
				{#each pending as item, i (item.title + item.detail)}
					{#if i > 0}<div class="divider"></div>{/if}
					<div class="row list-row">
						<span class="pending-icon"><Icon name={item.icon} size={16} /></span>
						<div class="grow">
							<p class="list-title">{item.title}</p>
							<p class="list-detail">{item.detail}</p>
						</div>
					</div>
				{/each}
			</div>
		{/if}

		{#if list(d.upcoming).length > 0}
			<p class="eyebrow">PRÓXIMAS CLASES</p>
			<div class="stack">
				{#each list(d.upcoming) as s (s.session_id)}
					{@const dp = dateParts(s)}
					<div class="card row session">
						<div class="date">
							<p class="day">{dp.day}</p>
							<p class="month">{dp.month}</p>
						</div>
						<div class="grow">
							<p class="list-title">{s.topic ?? 'Clase'}</p>
							<p class="list-detail">{timeRange(s)}</p>
						</div>
					</div>
				{/each}
			</div>
		{/if}

		{#if list(d.past).length > 0}
			<p class="eyebrow">CLASES ANTERIORES</p>
			<div class="stack">
				{#each list(d.past) as s (s.session_id)}
					{@const dp = dateParts(s)}
					<div class="card row session">
						<div class="date">
							<p class="day">{dp.day}</p>
							<p class="month">{dp.month}</p>
						</div>
						<div class="grow">
							<p class="list-title tight">{s.topic ?? 'Clase'}</p>
							<div class="chips">
								{#each pastChips(s) as chip (chip.text)}
									<span
										class="chip"
										class:chip-ok={chip.tone === 'ok'}
										class:chip-bad={chip.tone === 'bad'}
									>
										{chip.text}
									</span>
								{/each}
							</div>
						</div>
					</div>
				{/each}
			</div>
		{/if}
	{:else if loadError}
		<p class="subtitle">
			No se pudo cargar el panel.
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
		margin: 2px 0 var(--space-lg);
		font-size: 13px;
		color: var(--text-secondary);
	}

	.risk-link {
		color: inherit;
		text-decoration: none;
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
