<script lang="ts">
	import { onMount } from 'svelte';
	import { page } from '$app/state';
	import { ApiError, list } from '$lib/api/client';
	import type {
		AssessmentCreateDto,
		ClassDashboardDto,
		CompetencyCriteriaDto,
		GradingComponentDto,
		SessionSummaryDto,
	} from '$lib/api/dto';
	import {
		createAssessment,
		getClassDashboard,
		getGradingComponents,
	} from '$lib/api/endpoints/classes';
	import { getClassCriteria } from '$lib/api/endpoints/criteria';
	import { formatTimeHHMM, parseDateOnly } from '$lib/api/mappers';
	import AddEvidenceDialog from '$lib/components/AddEvidenceDialog.svelte';
	import Icon from '$lib/components/Icon.svelte';
	import TopBar from '$lib/components/TopBar.svelte';
	import { hapticTap } from '$lib/haptics';
	import { usesInternalGrading } from '$lib/stores';
	import { showToast } from '$lib/toast';

	const courseId = $derived(page.params.courseId ?? '');

	let ready = $state(false);
	let loadError = $state(false);
	let d = $state<ClassDashboardDto | null>(null);
	// Loaded for the "añadir evidencia" dialog, not for the dashboard itself:
	// the components are the sections evidence is filed under and the criterios
	// are what it can be linked to.
	let gradingComponents = $state<GradingComponentDto[]>([]);
	let criteriaGroups = $state<CompetencyCriteriaDto[]>([]);

	async function load(): Promise<void> {
		ready = false;
		loadError = false;
		try {
			const [dashboard, components, crits] = await Promise.all([
				getClassDashboard(courseId),
				getGradingComponents(courseId),
				getClassCriteria(courseId),
			]);
			d = dashboard;
			gradingComponents = list(components.components);
			criteriaGroups = list(crits.competencies);
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

	// Evidence filed from here is for the whole class — this is the screen that
	// speaks for the class rather than for one student. A single student's
	// evidence is added from their own grades screen instead.
	let showAddEvidence = $state(false);

	async function handleAddEvidence(body: AssessmentCreateDto): Promise<void> {
		showAddEvidence = false;
		try {
			await createAssessment(courseId, body);
			showToast('Evidencia añadida para toda la clase');
		} catch (err) {
			showToast(err instanceof ApiError ? err.message : 'No se pudo añadir la evidencia');
		}
	}

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

	const pastChips = (s: SessionSummaryDto): Array<{ text: string; tone: 'ok' | 'bad' }> => {
		const chips: Array<{ text: string; tone: 'ok' | 'bad' }> = [];
		if (s.present_count != null && s.roster_count != null) {
			chips.push({ text: `${s.present_count}/${s.roster_count} presente`, tone: 'ok' });
		}
		if (s.missing_grades != null && s.missing_grades > 0) {
			chips.push({ text: `${s.missing_grades} pendientes`, tone: 'bad' });
		}
		if (s.has_comments) {
			chips.push({ text: '✓ Comentarios', tone: 'ok' });
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
		<h1 class="clsname">{d.name}</h1>
		<span class="clscount">{d.roster_count} alumnos · {d.sessions_per_week} sesiones/semana</span>

		{#if d.next_session}
			{@const ns = d.next_session}
			{@const phase = sessionPhase(ns, now)}
			<div class="hero">
				<p class="hero-lbl">Hoy · {PHASE_LABEL[phase]}</p>
				<p class="hero-time">{formatTimeHHMM(ns.scheduled_start_at)}</p>
				<p class="hero-topic">
					{ns.topic ?? 'Sin tema asignado'} · termina {formatTimeHHMM(ns.scheduled_end_at)}
				</p>
				<a
					class="hero-start pressable"
					href="/class/{courseId}/lesson/{ns.session_id}"
					onclick={hapticTap}
				>
					Ver alumnos
					<Icon name="arrow-right" size={20} />
				</a>
			</div>
		{/if}

		<nav class="quiet">
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
			<button type="button" class="quiet-row pressable" onclick={() => (showAddEvidence = true)}>
				<span class="quiet-t">
					Añadir evidencia
					<span class="quiet-d">Para toda la clase — la nota se pone por alumno</span>
				</span>
				<span class="chevron"><Icon name="plus" size={18} /></span>
			</button>
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
			<p class="eyebrow">Clases anteriores</p>
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
							<span class="chips">
								{#each pastChips(s) as chip (chip.text)}
									<span
										class="chip"
										class:chip-ok={chip.tone === 'ok'}
										class:chip-bad={chip.tone === 'bad'}
									>
										{chip.text}
									</span>
								{/each}
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

{#if showAddEvidence}
	<AddEvidenceDialog
		usesInternalGrading={$usesInternalGrading}
		components={gradingComponents}
		competencies={criteriaGroups}
		scope="class"
		onsubmit={handleAddEvidence}
		oncancel={() => (showAddEvidence = false)}
	/>
{/if}

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

	/* Hero — today's session. The block itself is plain; the button is the only
	   dark element on the screen, which is what makes it the one obvious action. */
	.hero {
		margin: 32px 0 8px;
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
		margin: 12px 0 28px;
		font-size: 17px;
		color: var(--text-secondary);
	}

	.hero-start {
		display: flex;
		align-items: center;
		justify-content: center;
		gap: 10px;
		width: 100%;
		background: var(--text-primary);
		color: var(--on-primary);
		padding: 20px;
		border-radius: 14px;
		font-size: 19px;
		font-weight: 600;
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
		/* A <button> does not get full width or left alignment from the row layout
		   the way an <a> does — the second row is the "Añadir evidencia" action. */
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

	.lcard {
		display: flex;
		gap: 16px;
		min-width: 210px;
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
		display: block;
		font-size: 16px;
		font-weight: 500;
		line-height: 1.25;
	}

	.lcard-sub {
		display: block;
		margin-top: 4px;
		font-size: 13px;
		color: var(--text-secondary);
	}

	.chips {
		display: flex;
		gap: 6px;
		flex-wrap: wrap;
		margin-top: 10px;
	}

	/* Slightly roomier than the app-wide .chip, and never wrapped mid-chip. */
	.chip {
		padding: 3px 9px;
		white-space: nowrap;
	}
</style>
