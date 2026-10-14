<script lang="ts">
	import { Button, ErrorNotice, Icon, ListRow, LoadingState } from '$lib/design-system';
	import { onMount } from 'svelte';
	import { page } from '$app/state';
	import { list } from '$lib/api/client';
	import type { ClassDashboardDto, SessionSummaryDto } from '$lib/api/dto';
	import { getClassDashboard } from '$lib/api/endpoints/classes';
	import { formatTimeHHMM, parseDateOnly } from '$lib/api/mappers';
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

	// Wall-clock reference for the hero phase label, refreshed on an interval so
	// the "HOY · …" line flips SIN INICIAR → EN CURSO → FINALIZADA while the page
	// stays open, without a reload.
	let now = $state(Date.now());

	onMount(() => {
		load();
		const id = setInterval(() => {
			now = Date.now();
		}, 60_000);
		return () => clearInterval(id);
	});

	type SessionPhase = 'before' | 'during' | 'after';

	const PHASE_LABEL: Record<SessionPhase, string> = {
		before: 'Sin iniciar',
		during: 'En curso',
		after: 'Finalizada',
	};

	// Clock-derived, not status-derived. `next_session` only exists because the
	// server query filters `status` to scheduled/in_progress; the label itself is
	// purely where the wall clock sits between the two RFC3339 instants.
	// new Date(ts).getTime() is safe here — these are full instants, unlike the
	// bare `session_date` that goes through parseDateOnly.
	const sessionPhase = (s: SessionSummaryDto, ref: number): SessionPhase => {
		const start = new Date(s.scheduled_start_at).getTime();
		const end = new Date(s.scheduled_end_at).getTime();
		if (ref < start) return 'before';
		if (ref > end) return 'after';
		return 'during';
	};

	const timeRange = (s: SessionSummaryDto): string =>
		`${formatTimeHHMM(s.scheduled_start_at)} – ${formatTimeHHMM(s.scheduled_end_at)}`;

	const dateParts = (s: SessionSummaryDto): { day: string; month: string } => {
		const date = parseDateOnly(s.session_date);
		return {
			day: String(date.getDate()),
			month: date.toLocaleDateString('es-PE', { month: 'short' }).replace('.', '').toUpperCase(),
		};
	};
</script>

<svelte:head>
	<title>{d?.name ?? 'Clase'} — Panel</title>
</svelte:head>
<div class="view">
	<!-- Reached from the lesson screen as well as from Home now, so the arrow has
     to follow history rather than always landing on Home. -->
	<TopBar back="/" />

	<div class="body">
		{#if ready && d}
			<h1 class="screen-title">{d.name}</h1>
			<span class="clscount">{d.roster_count} alumnos · {d.sessions_per_week} sesiones/semana</span>

			{#if d.next_session}
				{@const ns = d.next_session}
				{@const phase = sessionPhase(ns, now)}
				<!-- Today's session is in neither rail, so the block itself has to be the
			     way into it: this is the rails' card, just larger. -->
				<a
					class="hero pressable"
					href="/class/{courseId}/lesson/{ns.session_id}?from=area"
					onclick={hapticTap}
				>
					<p class="hero-lbl">Hoy · {PHASE_LABEL[phase]}</p>
					<p class="hero-time">{formatTimeHHMM(ns.scheduled_start_at)}</p>
					<span class="hero-row">
						<span class="hero-topic">
							{ns.topic ?? 'Sin tema asignado'} · termina {formatTimeHHMM(ns.scheduled_end_at)}
						</span>
						<span class="chevron"><Icon name="chevron-right" size={18} /></span>
					</span>
					<Icon name="chevron-right" size={16} /></a
				>
			{/if}

			<nav class="quiet">
				<!-- First, because it is the row a teacher reaches for between classes;
			     the other two are set-up work. -->
				<ListRow href="/class/{courseId}/students" onclick={hapticTap}>
					<span class="quiet-t">
						Alumnos
						<span class="quiet-d">Niveles de logro por competencia</span>
					</span>
				</ListRow>
				<ListRow href="/class/{courseId}/plan" onclick={hapticTap}>
					<span class="quiet-t">
						Plan del trimestre
						<span class="quiet-d">Experiencias, criterios y sesiones</span>
					</span>
				</ListRow>
				<!-- A screen now, not a dialog: choosing the competencia and its criterios
			     is the decision that makes the evidence usable later, and in a 360px
			     modal it sat under the fold behind a scroll box. The trailing plus
			     stays — the row still creates something rather than going somewhere
			     to read. -->
				<ListRow
					href="/class/{courseId}/evidence/new?course={encodeURIComponent(d.name)}"
					onclick={hapticTap}
				>
					<span class="quiet-t">
						Añadir evidencia
						<span class="quiet-d">Una evaluación para toda la clase</span>
					</span>
				</ListRow>
			</nav>

			{#if list(d.upcoming).length > 0}
				<p class="eyebrow">Próximas clases</p>
				<div class="hscroll">
					{#each list(d.upcoming) as s (s.session_id)}
						{@const dp = dateParts(s)}
						<a
							class="lcard pressable"
							href="/class/{courseId}/lesson/{s.session_id}?from=area"
							onclick={hapticTap}
						>
							<span class="lcard-date">
								<span class="lcard-day">{dp.day}</span>
								<span class="lcard-mon">{dp.month}</span>
							</span>
							<span class="lcard-info">
								<span class="lcard-topic">{s.topic ?? 'Clase'}</span>
								<span class="lcard-sub">{timeRange(s)}</span>
							</span>
							<Icon name="chevron-right" size={16} /></a
						>
					{/each}
				</div>
			{/if}

			{#if list(d.past).length > 0}
				<p class="eyebrow tight">Clases anteriores</p>
				<p class="railhint">Toca una clase para dejarle una nota de voz.</p>
				<div class="hscroll">
					{#each list(d.past) as s (s.session_id)}
						{@const dp = dateParts(s)}
						<a
							class="lcard pressable"
							href="/class/{courseId}/lesson/{s.session_id}?from=area"
							onclick={hapticTap}
						>
							<span class="lcard-date">
								<span class="lcard-day">{dp.day}</span>
								<span class="lcard-mon">{dp.month}</span>
							</span>
							<span class="lcard-info">
								<span class="lcard-topic">{s.topic ?? 'Clase'}</span>
								<span class="lcard-sub">
									{timeRange(s)}
									<Icon name="mic" size={14} />
								</span>
							</span>
							<Icon name="chevron-right" size={16} /></a
						>
					{/each}
				</div>
			{/if}
		{:else if loadError}
			<ErrorNotice message="No se pudo cargar el panel." onretry={load} />
		{:else}<LoadingState label="Cargando…" />{/if}
	</div>
</div>

<style>
	.body {
		padding: 18px var(--mw-space-5) 30px;
	}

	.clscount {
		display: block;
		margin-top: 10px;
		font-size: var(--mw-type-label-size);
		color: var(--mw-ink-muted);
		font-family: var(--mw-font-sans);
		text-transform: uppercase;
	}

	.eyebrow.tight {
		margin-bottom: var(--mw-space-1);
	}

	.railhint {
		margin: 0 0 var(--mw-space-3);
		font-size: var(--mw-type-small-size);
		color: var(--mw-ink-muted);
	}

	.hero {
		display: block;
		margin: 18px 0 var(--mw-space-2);
		padding: 18px var(--mw-space-5);
		border-radius: var(--mw-radius-xl);
		background: var(--mw-accent);
		color: var(--mw-on-accent);
		box-shadow: var(--mw-shadow-card);
	}

	.hero-row {
		display: flex;
		align-items: center;
		gap: var(--mw-space-3);
		margin-top: 10px;
	}

	.hero-lbl {
		margin: 0;
		font-size: var(--mw-type-label-size);
		letter-spacing: 0.04em;
		color: var(--mw-on-accent);
		font-family: var(--mw-font-sans);
		text-transform: uppercase;
	}

	.hero-time {
		margin: 2px 0 0;
		font-size: var(--mw-type-title-size);
		font-weight: 800;
		letter-spacing: -0.02em;
		line-height: 1.05;
	}

	.hero-topic {
		flex: 1;
		min-width: 0;
		font-size: var(--mw-type-small-size);
		font-weight: 600;
		color: var(--mw-on-accent);
	}

	.hero .chevron {
		color: var(--mw-on-accent);
	}

	.quiet {
		margin-top: var(--mw-space-4);
		margin-bottom: 34px;
		display: flex;
		flex-direction: column;
	}

	.quiet-t {
		flex: 1;
		font-size: var(--mw-type-heading-size);
		font-weight: 700;
		letter-spacing: -0.01em;
	}

	.quiet-d {
		display: block;
		margin-top: 2px;
		font-size: var(--mw-type-caption-size);
		font-weight: 400;
		color: var(--mw-ink-muted);
	}

	.chevron {
		display: flex;
		flex-shrink: 0;
		color: var(--mw-ink-muted);
	}

	.hscroll {
		display: flex;
		gap: var(--mw-space-3);
		overflow-x: auto;
		padding: 0 var(--mw-space-5) var(--mw-space-2);
		margin: 0 -20px 30px;
		scroll-snap-type: x proximity;
	}

	.hscroll::-webkit-scrollbar {
		height: 0;
	}

	.lcard {
		display: flex;
		gap: var(--mw-space-4);
		width: max-content;
		min-width: 190px;
		max-width: 300px;
		flex: 0 0 auto;
		scroll-snap-align: start;
		padding: 14px var(--mw-space-4);
		background: var(--mw-surface-tint);
		border-radius: var(--mw-radius-xl);
		color: inherit;
	}

	.lcard-date {
		width: 46px;
		flex-shrink: 0;
		text-align: center;
	}

	.lcard-day {
		display: block;
		font-size: var(--mw-type-title-size);
		font-weight: 800;
		letter-spacing: -0.02em;
		line-height: 1.1;
		color: var(--mw-accent);
	}

	.lcard-mon {
		font-size: var(--mw-type-label-size);
		color: var(--mw-ink-muted);
		font-family: var(--mw-font-sans);
	}

	.lcard-info {
		flex: 1;
		min-width: 0;
	}

	.lcard-topic {
		display: -webkit-box;
		-webkit-line-clamp: 2;
		line-clamp: 2;
		-webkit-box-orient: vertical;
		overflow: hidden;
		font-size: var(--mw-type-body-size);
		font-weight: 700;
		letter-spacing: -0.01em;
		line-height: 1.25;
	}

	.lcard-sub {
		display: flex;
		align-items: center;
		gap: 6px;
		margin-top: var(--mw-space-1);
		font-family: var(--mw-font-sans);
		font-size: var(--mw-type-label-size);
		color: var(--mw-ink-muted);
	}

	.lcard-sub :global(.ic) {
		color: var(--mw-accent);
	}
</style>
