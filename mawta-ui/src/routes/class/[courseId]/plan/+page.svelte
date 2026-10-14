<script lang="ts">
	import {
		Button,
		Card,
		Context,
		EmptyState,
		ErrorNotice,
		Icon,
		IconButton,
		LoadingState,
		StatusList,
	} from '$lib/design-system';
	import { onMount } from 'svelte';
	import { page } from '$app/state';
	import { goto } from '$app/navigation';
	import { list } from '$lib/api/client';
	import type { ClassPlanDto, NonTeachingDayKind, PlanExperienceDto } from '$lib/api/dto';
	import { getClassPlan } from '$lib/api/endpoints/planning';
	import TopBar from '$lib/components/TopBar.svelte';
	import { hapticTap } from '$lib/haptics';
	import { buildTimeline, offRuns, percentOf, spanOf } from '$lib/timeline';

	let timeline = $state<HTMLDivElement | null>(null);
	const courseId = $derived(page.params.courseId ?? '');

	let ready = $state(false);
	let loadError = $state(false);
	let plan = $state<ClassPlanDto | null>(null);

	async function load(): Promise<void> {
		ready = false;
		loadError = false;
		try {
			plan = await getClassPlan(courseId);
			ready = true;
		} catch {
			loadError = true;
		}
	}

	onMount(load);

	// Opening an experience always lands on its summary: the hub from where every
	// step is reachable, a draft included (the summary flags what is missing).
	function openExperience(experience: PlanExperienceDto): void {
		hapticTap();
		void goto(`/class/${courseId}/plan/${experience.id}/summary`);
	}

	// The plan screen's whole read is one request; a failed load only offers
	// the retry, the same as the criteria screen.
	const experiences = $derived(list(plan?.experiences));
	// The bars and the cards share this order, so "1" is the same experience in both.
	const orderedExperiences = $derived(
		[...experiences].sort((a, b) =>
			a.starts_on < b.starts_on ? -1 : a.starts_on > b.starts_on ? 1 : 0
		)
	);
	const competencies = $derived(list(plan?.competencies));
	const nonTeachingDays = $derived(list(plan?.non_teaching_days));

	// ---- dates, in the app's Spanish ----

	const MONTHS = [
		'ene',
		'feb',
		'mar',
		'abr',
		'may',
		'jun',
		'jul',
		'ago',
		'sep',
		'oct',
		'nov',
		'dic',
	];

	// "YYYY-MM-DD" → local midnight, so no UTC shift ever moves a class date.
	function fromISO(date: string): Date {
		const [y, m, d] = date.split('-').map(Number);
		return new Date(y ?? 1970, (m ?? 1) - 1, d ?? 1);
	}

	// "15 jun"
	function fmtDate(date: string): string {
		const day = fromISO(date);
		return `${day.getDate()} ${MONTHS[day.getMonth()]}`;
	}

	// "15 jun – 10 jul"
	function fmtRange(from: string, to: string): string {
		return `${fmtDate(from)} – ${fmtDate(to)}`;
	}

	// ---- the term as weeks ----

	// Weeks are the column headers. Each week is split into its class days, so the
	// track counts classes: consecutive classes touch and days without class take
	// no space. A week with no class is a normal-width week in its own colour.
	const track = $derived(
		plan ? buildTimeline(plan.term.starts_on, plan.term.ends_on, plan.scheduled_class_days) : null
	);
	const weekCount = $derived(track?.weekCount ?? 0);

	// Short spans can't hold text. Measured in weeks: a week or more shows the
	// title, from 0.6 of a week the number only, below that an empty pill.
	function barSize(weeks: number): 'full' | 'number' | 'none' {
		if (weeks >= 1.5) return 'full';
		if (weeks >= 0.6) return 'number';
		return 'none';
	}

	// "5 oct": the day each week opens on, counted from the term's first day.
	function weekStart(week: number): string {
		if (!plan) return '';
		const day = fromISO(plan.term.starts_on);
		day.setDate(day.getDate() + (week - 1) * 7);
		return `${day.getDate()} ${MONTHS[day.getMonth()]}`;
	}

	const weekNumbers = $derived.by(() => {
		const weeks: number[] = [];
		for (let week = 1; week <= weekCount; week++) weeks.push(week);
		return weeks;
	});

	// Experience blocks, placed on the class-day track. The server rejects
	// overlapping experiences, so they normally share one row. A lane is used only
	// if two spans ever collide: the second one moves down instead of being drawn
	// on top. The number is the card's position, even when a block is skipped.
	const expBlocks = $derived.by(() => {
		const laneEnds: number[] = [];
		return orderedExperiences.flatMap((experience, index) => {
			const span = track ? spanOf(track, experience.starts_on, experience.ends_on) : null;
			if (!span) return [];
			let lane = laneEnds.findIndex((end) => end <= span.start);
			if (lane === -1) lane = laneEnds.push(span.end) - 1;
			else laneEnds[lane] = span.end;
			const weeks = span.end - span.start;
			return [
				{
					id: experience.id,
					number: index + 1,
					title: experience.title,
					classes: experience.class_dates,
					size: barSize(weeks),
					left: percentOf(span.start, weekCount),
					width: percentOf(weeks, weekCount),
					lane: lane + 1,
				},
			];
		});
	});

	const lanes = $derived(Math.max(1, ...expBlocks.map((block) => block.lane)));

	// Non-teaching days mark the class slots they take, merged while consecutive
	// class days share a kind and label. A feriado is a dot; vacations and gestión
	// tint their slots. The title says which day it is.
	const OFF_TEXT: Record<NonTeachingDayKind, string> = {
		feriado: 'feriado',
		vacaciones: 'vacaciones',
		gestion: 'gestión',
	};

	const offMarks = $derived(track ? offRuns(track, nonTeachingDays) : []);

	// A feriado is a dot under the line, at the middle of its class slot. It never
	// covers an experience: the bar shows the experience, the dot shows the day.
	const feriadoDots = $derived(
		offMarks
			.filter((run) => run.kind === 'feriado')
			.map((run, index) => ({
				id: index,
				left: percentOf((run.start + run.end) / 2, weekCount),
				label: run.label ?? OFF_TEXT.feriado,
			}))
	);

	// Vacations and gestión take class slots too. They get the same tint as a week
	// without classes, behind the bars, so there is one "sin clases" look and
	// nothing covers an experience.
	const offSlots = $derived(
		offMarks
			.filter((run) => run.kind !== 'feriado')
			.map((run, index) => ({
				id: index,
				label: run.label ?? OFF_TEXT[run.kind],
				left: percentOf(run.start, weekCount),
				width: percentOf(run.end - run.start, weekCount),
			}))
	);

	// The track is as tall as its bars: 44px each, 3px apart.
	const trackHeight = $derived(lanes * 47 - 3);

	// ---- status and coverage, written as text ----

	// Only competencias this term plans get an evidence count; below the minimum
	// the line says what the conclusion needs. Nothing is said about the others.
	function evidenceText(competency: { in_term: boolean; evidences_this_term: number }): string {
		if (!competency.in_term) return '';
		const n = competency.evidences_this_term;
		const count = n === 1 ? '1 evidencia' : `${n} evidencias`;
		return n < 2
			? ` ${count} en el trimestre; Mawta necesita al menos 2 para la conclusión.`
			: ` ${count} en el trimestre.`;
	}

	const EXPERIENCE_STATUS: Record<string, string> = {
		borrador: 'Borrador',
		planificada: 'Planificada',
	};

	const COMPETENCY_STATUS: Record<string, string> = {
		planificada: 'Planificada',
		toca: 'Toca este trimestre',
		puede_esperar: 'Puede esperar',
	};

	// The experience's competencies together: how many of the capabilities it
	// touches already have a criterio.
	function coverageOf(experience: PlanExperienceDto): { withCriteria: number; total: number } {
		const comps = list(experience.competencies);
		return {
			withCriteria: comps.reduce((count, comp) => count + comp.capabilities_with_criteria, 0),
			total: comps.reduce((count, comp) => count + comp.capabilities_total, 0),
		};
	}

	// What the tracking reads from: the periods the competencia was already
	// worked in this year, in the prototype's words.
	function termsWorkedText(terms: number[]): string {
		if (terms.length === 0) return 'Aún no se trabaja este año.';
		return `Ya se trabajó en ${terms.map((term) => `T${term}`).join(' y ')}.`;
	}
</script>

<svelte:head>
	<title>Tu trimestre</title>
</svelte:head>
<div class="view">
	<TopBar back={`/class/${courseId}`} />

	<div class="body">
		{#if ready && plan}
			<h1 class="screen-title">Tu trimestre</h1>
			<p class="screen-sub">
				{plan.term.name} · {fmtRange(plan.term.starts_on, plan.term.ends_on)} ·
				{plan.class_dates_total} clases
			</p>

			<div class="mw-section">
				<p class="eyebrow">Tu trimestre por semanas</p>
				<div class="timeline" style="--cols:{weekCount};--lanes:{lanes}">
					<div class="timeline-actions">
						<IconButton
							icon="chevron-left"
							label="Semanas anteriores"
							onclick={() => timeline?.scrollBy({ left: -240 })}
						/><span class="meta">{fmtRange(plan.term.starts_on, plan.term.ends_on)}</span
						><IconButton
							icon="chevron-right"
							label="Semanas siguientes"
							onclick={() => timeline?.scrollBy({ left: 240 })}
						/>
					</div>
					<div
						class="timeline-scroll"
						bind:this={timeline}
						role="region"
						aria-label="Calendario por semanas"
					>
						<div class="tl-head">
							{#each weekNumbers as week (week)}<span
									><b>{weekStart(week)}</b><small>Sem {week}</small></span
								>{/each}
						</div>
						<div class="tl-track" style="height:{trackHeight}px">
							{#each weekNumbers as week (week)}
								<span
									class="tl-week"
									class:tl-week-off={track !== null && !track.weekHasClasses[week - 1]}
									style="grid-column:{week}"
								></span>
							{/each}
							{#each expBlocks as block (block.id)}
								<span
									class="tl-block tl-{block.size}"
									title={`${block.number}. ${block.title}`}
									style="left:calc({block.left}% + 1.5px);width:calc({block.width}% - 3px);top:{(block.lane -
										1) *
										47}px"
								>
									{#if block.size !== 'none'}<b class="tl-num" aria-hidden="true">{block.number}</b
										>{/if}
									{#if block.size === 'full'}
										<span class="tl-title">{block.title}</span>
										<small>{block.classes} clases</small>
									{/if}
								</span>
							{/each}
							<!-- Behind the bars (they are raised): a vacation never covers an experience. -->
							{#each offSlots as slot (slot.id)}
								<span
									class="tl-slot-off"
									style="left:calc({slot.left}% + 1.5px);width:calc({slot.width}% - 3px)"
									title={slot.label}
								></span>
							{/each}
						</div>
						<!-- Outside the track, so the dots never stretch the week columns. -->
						<div class="tl-marks">
							{#each feriadoDots as dot (dot.id)}
								<i class="tl-dot" style="left:{dot.left}%" title={dot.label}></i>
							{/each}
						</div>
					</div>
					<div class="legend">
						<span><span class="sw sw-exp"></span>Experiencia (n.º como en la lista)</span>
						<span><span class="sw-dot"></span>Feriado</span>
						<span><span class="sw sw-week-off"></span>Semana sin clases</span>
					</div>
				</div>
			</div>

			<div class="mw-section">
				<Context>
					<p class="eyebrow">Competencias este trimestre</p>
					<StatusList
						items={competencies.map((competency) => ({
							id: competency.id,
							name: competency.name,
							status:
								competency.status === 'planificada'
									? 'done'
									: competency.status === 'toca'
										? 'due'
										: 'waiting',
							label: COMPETENCY_STATUS[competency.status] ?? competency.status,
							detail: `${competency.capabilities_covered_this_term} de ${competency.capabilities_total} capacidades con criterio.${evidenceText(competency)} ${competency.status !== 'planificada' ? termsWorkedText(list(competency.terms_worked)) : ''}`,
						}))}
					/>
				</Context>
			</div>

			<div class="mw-section">
				{#if experiences.length > 0}
					<p class="eyebrow">Experiencias · {experiences.length}</p>
					<div class="stack">
						{#each orderedExperiences as experience, index (experience.id)}
							{@const coverage = coverageOf(experience)}
							<Card onclick={() => openExperience(experience)}>
								<div class="row exp-head">
									<span class="exp-num"
										><span class="mw-sr-only">Experiencia </span>{index + 1}</span
									>
									<p class="grow exp-title">{experience.title}</p>
									<p
										class="mw-badge {experience.status === 'planificada'
											? 'mw-badge--success'
											: ''}"
									>
										{EXPERIENCE_STATUS[experience.status] ?? experience.status}
									</p>
								</div>
								<p class="meta">
									{fmtRange(experience.starts_on, experience.ends_on)} · {experience.class_dates}
									clases
								</p>
								<p class="exp-comps">
									{list(experience.competencies)
										.map((competency) => competency.name)
										.join(' · ')}
								</p>
								<p class="exp-coverage">
									{coverage.withCriteria} de {coverage.total} capacidades con criterio
								</p>
								{#if experience.pending_proposals > 0}
									<p class="exp-coverage">
										{experience.pending_proposals === 1
											? '1 propuesta de Mawta por revisar'
											: `${experience.pending_proposals} propuestas de Mawta por revisar`}
									</p>
								{/if}
							</Card>
						{/each}
					</div>
				{:else}
					<Card>
						<EmptyState
							icon="calendar"
							title="Aún no hay experiencias en este trimestre"
							description="Cuéntale a Mawta tu idea: detecta las competencias y arma la propuesta con criterios, evidencias y sesiones."
						/>
					</Card>
				{/if}

				<Button
					variant="primary"
					block
					class="create"
					href={`/class/${courseId}/plan/new`}
					onclick={hapticTap}
				>
					<Icon name="plus" size={16} /> Crear experiencia
				</Button>
			</div>
		{:else if loadError}
			<ErrorNotice message="No se pudo cargar…" onretry={load} />
		{:else}<LoadingState label="Cargando…" />{/if}
	</div>
</div>

<style>
	.timeline-actions {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--mw-space-2);
		margin-bottom: var(--mw-space-2);
	}
	.timeline-scroll {
		overflow-x: auto;
		padding-bottom: var(--mw-space-2);
	}
	.tl-title {
		display: block;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.screen-sub {
		margin: 10px 0 0;
	}

	.timeline {
		--cols: 1;
	}

	/* Head, track and marks share one width, so a percentage of the track is a day. */
	.tl-head,
	.tl-track {
		display: grid;
		grid-template-columns: repeat(var(--cols), minmax(80px, 1fr));
		width: max(100%, calc(var(--cols) * 80px));
	}

	.tl-head span {
		text-align: center;
		font-family: var(--mw-font-sans);
		font-size: var(--mw-type-label-size);
		color: var(--mw-ink-muted);
		white-space: nowrap;
	}

	.tl-head b {
		display: block;
		font-weight: 600;
		color: var(--mw-ink-secondary);
	}

	.tl-head small {
		font-size: inherit;
	}

	/* One row of bars, as tall as the lanes in use (the lane gap is 3px). */
	.tl-track {
		position: relative;
		grid-template-rows: 1fr;
		margin-top: 6px;
	}

	/* Each week column is inset 1.5px, so two columns show the same 3px gap as before. */
	.tl-week {
		margin: 0 1.5px;
		border-radius: var(--mw-radius-md);
		background: var(--mw-surface-tint);
	}

	.tl-block {
		position: absolute;
		top: 0;
		height: 44px;
		border-radius: var(--mw-radius-md);
		background: var(--mw-accent);
		color: var(--mw-on-accent);
		font-size: var(--mw-type-label-size);
		font-weight: 700;
		line-height: 1.25;
		padding: 6px 7px;
		overflow: hidden;
		z-index: var(--mw-z-raised);
	}

	/* Each experience is its own pill: a card-coloured border separates neighbours. */
	.tl-block {
		padding-left: 30px;
		border: 2px solid var(--mw-surface-card);
		background-clip: padding-box;
	}

	/* Too short for anything inside: the pill keeps its colour and the card says the rest. */
	.tl-block.tl-none {
		padding: 0;
	}

	/* The number matches the card in the list; it stays visible when the title is clipped. */
	.tl-num {
		position: absolute;
		left: 5px;
		top: 50%;
		display: grid;
		place-items: center;
		width: 18px;
		height: 18px;
		margin-top: -9px;
		border-radius: 50%;
		background: var(--mw-surface-card);
		color: var(--mw-accent);
		font-size: var(--mw-type-label-size);
		font-weight: 800;
		line-height: 1;
	}

	.exp-num {
		display: grid;
		place-items: center;
		flex: 0 0 auto;
		width: 22px;
		height: 22px;
		margin-right: var(--mw-space-2);
		border-radius: 50%;
		background: var(--mw-accent);
		color: var(--mw-on-accent);
		font-size: var(--mw-type-label-size);
		font-weight: 800;
	}

	.tl-block small {
		display: block;
		margin-top: 2px;
		font-family: var(--mw-font-sans);
		font-size: var(--mw-type-label-size);
		font-weight: 500;
		opacity: 0.85;
	}

	/* Vacation or gestión slots: the same tint as a week without classes, behind the bars. */
	.tl-slot-off {
		position: absolute;
		top: 0;
		bottom: 0;
		border-radius: var(--mw-radius-md);
		background: var(--mw-surface-card);
		border: 1px solid var(--mw-line);
	}

	/* The row under the track: same width, so a percentage here is the same day. */
	.tl-marks {
		position: relative;
		width: max(100%, calc(var(--cols) * 80px));
		height: 8px;
		margin-top: var(--mw-space-1);
	}

	/* A feriado: a dot in the row under the track, centred on its class slot. */
	.tl-dot {
		position: absolute;
		top: 50%;
		transform: translate(-50%, -50%);
		width: 6px;
		height: 6px;
		border-radius: 50%;
		background: var(--mw-ink-muted);
	}

	/* A week with no class day keeps its width; only its colour says so. */
	.tl-week-off {
		background: var(--mw-surface-card);
		border: 1px solid var(--mw-line);
	}

	.legend {
		flex-wrap: wrap;
		display: flex;
		gap: 14px;
		margin-top: 10px;
		font-size: var(--mw-type-label-size);
		color: var(--mw-ink-muted);
	}

	.legend > span {
		display: inline-flex;
		align-items: center;
		gap: 6px;
	}

	.sw {
		width: 12px;
		height: 12px;
		border-radius: 3px;
	}

	.sw-exp {
		background: var(--mw-accent);
	}

	.sw-dot {
		width: 6px;
		height: 6px;
		border-radius: 50%;
		background: var(--mw-ink-muted);
	}

	.sw-week-off {
		width: 12px;
		height: 12px;
		border-radius: 3px;
		background: var(--mw-surface-card);
		border: 1px solid var(--mw-line);
	}

	.stack {
		display: flex;
		flex-direction: column;
		gap: var(--mw-space-2);
	}

	.row.exp-head {
		gap: var(--mw-space-2);
	}

	.exp-title {
		margin: 0;
		font-size: var(--mw-type-body-size);
		font-weight: 700;
		letter-spacing: -0.01em;
		line-height: 1.3;
	}

	.exp-comps {
		margin: 6px 0 0;
		font-size: var(--mw-type-caption-size);
		line-height: 1.4;
		color: var(--mw-ink-secondary);
	}

	.exp-coverage {
		margin: 3px 0 0;
		font-size: var(--mw-type-caption-size);
		color: var(--mw-ink-muted);
	}

	.view :global(.create) {
		margin-top: var(--mw-space-3);
	}
</style>
