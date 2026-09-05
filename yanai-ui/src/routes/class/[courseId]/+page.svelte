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

<!-- Reached from the lesson screen as well as from Home now, so the arrow has
     to follow history rather than always landing on Home. -->
<TopBar back="/" useHistory />

<div class="body">
	{#if ready && d}
		<h1 class="clsname">{d.name}</h1>
		<span class="clscount">{d.roster_count} alumnos · {d.sessions_per_week} sesiones/semana</span>

		{#if d.next_session}
			{@const ns = d.next_session}
			{@const phase = sessionPhase(ns, now)}
			<!-- Today's session is in neither rail, so the block itself has to be the
			     way into it: this is the rails' card, just larger. -->
			<a class="hero pressable" href="/class/{courseId}/lesson/{ns.session_id}" onclick={hapticTap}>
				<p class="hero-lbl">Hoy · {PHASE_LABEL[phase]}</p>
				<p class="hero-time">{formatTimeHHMM(ns.scheduled_start_at)}</p>
				<span class="hero-row">
					<span class="hero-topic">
						{ns.topic ?? 'Sin tema asignado'} · termina {formatTimeHHMM(ns.scheduled_end_at)}
					</span>
					<span class="chevron"><Icon name="chevron-right" size={18} /></span>
				</span>
			</a>
		{/if}

		<nav class="quiet">
			<!-- First, because it is the row a teacher reaches for between classes;
			     the other two are set-up work. -->
			<a class="quiet-row pressable" href="/class/{courseId}/students" onclick={hapticTap}>
				<span class="quiet-t">
					Alumnos
					<span class="quiet-d">Niveles de logro por competencia</span>
				</span>
				<span class="chevron"><Icon name="chevron-right" size={18} /></span>
			</a>
			<a
				class="quiet-row pressable"
				href="/class/{courseId}/criteria?course={encodeURIComponent(d.name)}"
				onclick={hapticTap}
			>
				<span class="quiet-t">
					Criterios de evaluación
					<span class="quiet-d">Lo que valoras en cada competencia</span>
				</span>
				<span class="chevron"><Icon name="chevron-right" size={18} /></span>
			</a>
			<!-- A screen now, not a dialog: choosing the competencia and its criterios
			     is the decision that makes the evidence usable later, and in a 360px
			     modal it sat under the fold behind a scroll box. The trailing plus
			     stays — the row still creates something rather than going somewhere
			     to read. -->
			<a
				class="quiet-row pressable"
				href="/class/{courseId}/evidence/new?course={encodeURIComponent(d.name)}"
				onclick={hapticTap}
			>
				<span class="quiet-t">
					Añadir evidencia
					<span class="quiet-d">Una evaluación para toda la clase</span>
				</span>
				<span class="chevron"><Icon name="plus" size={18} /></span>
			</a>
		</nav>

		{#if list(d.upcoming).length > 0}
			<p class="eyebrow">Próximas clases</p>
			<div class="hscroll">
				{#each list(d.upcoming) as s (s.session_id)}
					{@const dp = dateParts(s)}
					<a
						class="lcard pressable"
						href="/class/{courseId}/lesson/{s.session_id}"
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
					</a>
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
						href="/class/{courseId}/lesson/{s.session_id}"
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
					</a>
				{/each}
			</div>
		{/if}
	{:else if loadError}
		<p class="clscount">
			No se pudo cargar el panel.
			<button class="pill-light pressable" onclick={load}>Reintentar</button>
		</p>
	{/if}
</div>

<style>
	/* This screen sets its own gutter: the session rails bleed to the phone edge
	   by cancelling it with a negative margin, so the number has to be known here
	   rather than inherited from the global .body padding. */
	.body {
		padding: 22px 18px 30px;
	}

	/* Section labels here are smaller, bolder and wider-tracked than the app-wide
	   .eyebrow, and are uppercased by CSS rather than in the markup. */
	.eyebrow {
		margin: 0 0 12px;
		font-size: 11px;
		font-weight: 600;
		letter-spacing: 0.08em;
		text-transform: uppercase;
	}

	.clsname {
		margin: 0;
		font-size: 30px;
		font-weight: 600;
		letter-spacing: -0.02em;
		line-height: 1.12;
	}

	.clscount {
		display: block;
		margin-top: 8px;
		font-size: 13px;
		color: var(--text-muted);
		font-family: var(--font-mono);
	}

	/* Section labels sit tight above a hint line where one follows. */
	.eyebrow.tight {
		margin-bottom: 4px;
	}

	.railhint {
		margin: 0 0 12px;
		font-size: 13px;
		color: var(--text-muted);
	}

	/* Hero — today's session, and a link into it. The screen has no dark element
	   at all now: it is a launcher, not a screen with one obvious action. */
	.hero {
		display: block;
		margin: 32px 0 8px;
		color: inherit;
	}

	.hero-row {
		display: flex;
		align-items: center;
		gap: 12px;
		margin-top: 12px;
	}

	.hero-lbl {
		margin: 0 0 14px;
		font-size: 12px;
		letter-spacing: 0.12em;
		color: var(--text-muted);
		font-family: var(--font-mono);
		text-transform: uppercase;
	}

	.hero-time {
		margin: 0;
		font-size: 40px;
		font-weight: 600;
		letter-spacing: -0.02em;
		line-height: 1;
	}

	.hero-topic {
		flex: 1;
		min-width: 0;
		font-size: 17px;
		color: var(--text-secondary);
	}

	/* Quiet nav list — hairline-ruled rows, top and bottom. */
	.quiet {
		margin-top: 16px;
		margin-bottom: 34px;
		display: flex;
		flex-direction: column;
	}

	.quiet-row {
		display: flex;
		align-items: center;
		gap: 12px;
		padding: 20px 4px;
		color: inherit;
		border-bottom: 0.5px solid var(--border);
		width: 100%;
		text-align: left;
	}

	.quiet-row:first-child {
		border-top: 0.5px solid var(--border);
	}

	.quiet-t {
		flex: 1;
		font-size: 17px;
		font-weight: 500;
	}

	.quiet-d {
		display: block;
		margin-top: 2px;
		font-size: 13px;
		font-weight: 400;
		color: var(--text-muted);
	}

	.chevron {
		display: flex;
		flex-shrink: 0;
		color: var(--text-muted);
	}

	/* Session rails — bleed past the body gutter so a card can sit half-cut at the
	   edge, which is what tells you the row scrolls. */
	.hscroll {
		display: flex;
		gap: 12px;
		overflow-x: auto;
		padding: 0 18px 8px;
		margin: 0 -18px 30px;
		scroll-snap-type: x proximity;
	}

	.hscroll::-webkit-scrollbar {
		height: 0;
	}

	/* The card follows its topic rather than holding one width: a one-word topic
	   takes little room and a long one gets to 300px before it clips, which is
	   about twice what a fixed 210px card could show. */
	.lcard {
		display: flex;
		gap: 16px;
		width: max-content;
		min-width: 190px;
		max-width: 300px;
		flex: 0 0 auto;
		scroll-snap-align: start;
		padding: 16px;
		border: 0.5px solid var(--border);
		border-radius: 14px;
		color: inherit;
	}

	.lcard-date {
		width: 46px;
		flex-shrink: 0;
		text-align: center;
	}

	.lcard-day {
		display: block;
		font-size: 24px;
		font-weight: 600;
		line-height: 1;
	}

	.lcard-mon {
		font-size: 11px;
		color: var(--text-muted);
		font-family: var(--font-mono);
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
		font-size: 16px;
		font-weight: 500;
		line-height: 1.25;
	}

	.lcard-sub {
		display: flex;
		align-items: center;
		gap: 8px;
		margin-top: 4px;
		font-size: 13px;
		color: var(--text-secondary);
	}

	/* Only past cards carry it: it says the card leads somewhere you can record,
	   which is not yet true of a session that has not happened. */
	.lcard-sub :global(.ic) {
		color: var(--text-muted);
	}
</style>
