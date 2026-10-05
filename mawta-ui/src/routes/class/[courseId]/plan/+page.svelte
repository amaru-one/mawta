<script lang="ts">
	import { onMount } from 'svelte';
	import { page } from '$app/state';
	import { list } from '$lib/api/client';
	import type { ClassPlanDto, NonTeachingDayKind, PlanExperienceDto } from '$lib/api/dto';
	import { getClassPlan } from '$lib/api/endpoints/planning';
	import Icon from '$lib/components/Icon.svelte';
	import TopBar from '$lib/components/TopBar.svelte';
	import { hapticTap } from '$lib/haptics';

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

	// The plan screen's whole read is one request; a failed load only offers
	// the retry, the same as the criteria screen.
	const experiences = $derived(list(plan?.experiences));
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
	const DAY_MS = 86400000;

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

	// Weeks are counted from the term's first day: week 1 opens the term, and
	// every experience and non-teaching range is placed by the week its dates
	// fall in. A stretch without experiences is just empty weeks — nothing
	// warns, because a gap is not a problem.
	const weekCount = $derived.by(() => {
		if (!plan) return 0;
		const days = Math.round(
			(fromISO(plan.term.ends_on).getTime() - fromISO(plan.term.starts_on).getTime()) / DAY_MS
		);
		return Math.floor(days / 7) + 1;
	});

	function weekOf(date: string): number {
		if (!plan) return 1;
		const days = Math.round(
			(fromISO(date).getTime() - fromISO(plan.term.starts_on).getTime()) / DAY_MS
		);
		return Math.min(Math.max(Math.floor(days / 7) + 1, 1), weekCount);
	}

	const weekNumbers = $derived.by(() => {
		const weeks: number[] = [];
		for (let week = 1; week <= weekCount; week++) weeks.push(week);
		return weeks;
	});

	// Experience blocks, placed by their dates.
	const expBlocks = $derived(
		experiences.map((experience) => ({
			id: experience.id,
			title: experience.title,
			classes: experience.class_dates,
			from: weekOf(experience.starts_on),
			to: weekOf(experience.ends_on),
		}))
	);

	// Non-teaching days: a range longer than one day is drawn over the weeks it
	// covers; a single day is a dot under its week.
	const OFF_TEXT: Record<NonTeachingDayKind, string> = {
		feriado: 'feriado',
		vacaciones: 'vacaciones',
		gestion: 'gestión',
	};

	const offBlocks = $derived(
		nonTeachingDays
			.filter((day) => day.from !== day.to)
			.map((day, index) => ({
				id: `${day.from}-${index}`,
				text: OFF_TEXT[day.kind] ?? day.kind,
				label: day.label ?? OFF_TEXT[day.kind] ?? day.kind,
				from: weekOf(day.from),
				to: weekOf(day.to),
			}))
	);

	const offDots = $derived(
		nonTeachingDays
			.filter((day) => day.from === day.to)
			.map((day) => ({
				week: weekOf(day.from),
				label: day.label ?? OFF_TEXT[day.kind] ?? day.kind,
			}))
	);

	// ---- status and coverage, written as text ----

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

	const dueCount = $derived(
		competencies.filter((competency) => competency.status === 'toca').length
	);
</script>

<svelte:head>
	<title>Tu trimestre</title>
</svelte:head>

<TopBar back={`/class/${courseId}`} useHistory />

<div class="body">
	{#if ready && plan}
		<h1 class="screen-title">Tu trimestre</h1>
		<p class="screen-sub">
			{plan.term.name} · {fmtRange(plan.term.starts_on, plan.term.ends_on)} ·
			{plan.class_dates_total} clases
		</p>

		<div class="section">
			<p class="eyebrow">Tu trimestre por semanas</p>
			<div class="timeline" style="--cols:{weekCount}">
				<div class="tl-head">
					{#each weekNumbers as week (week)}<span>{week}</span>{/each}
				</div>
				<div class="tl-track">
					{#each weekNumbers as week (week)}
						<span class="tl-week" style="grid-column:{week}"></span>
					{/each}
					{#each offBlocks as block (block.id)}
						<span
							class="tl-off"
							style="grid-column:{block.from} / {block.to + 1}"
							title={block.label}
						>
							{block.text}
						</span>
					{/each}
					{#each expBlocks as block (block.id)}
						<span class="tl-block" style="grid-column:{block.from} / {block.to + 1}">
							{block.title}
							<small>{block.classes} clases</small>
						</span>
					{/each}
				</div>
				<div class="tl-marks">
					{#each weekNumbers as week (week)}
						{@const dot = offDots.find((item) => item.week === week)}
						{#if dot}
							<i class="tl-dot" title={dot.label}></i>
						{:else}
							<span></span>
						{/if}
					{/each}
				</div>
				<div class="legend">
					<span><span class="sw sw-exp"></span>Experiencia</span>
					<span><span class="sw sw-off"></span>Semana sin clases</span>
					<span><span class="sw-dot"></span>Día sin clases</span>
				</div>
			</div>
		</div>

		<div class="section">
			<div class="context-card">
				<div class="label-row">
					<p class="eyebrow">Competencias este trimestre</p>
					<p class="meta">{dueCount > 0 ? `${dueCount} por trabajar` : 'al día'}</p>
				</div>
				{#each competencies as competency (competency.id)}
					<div class="comp-row">
						<div class="row comp-head">
							<p class="grow comp-name">{competency.name}</p>
							<p class="comp-status">
								{COMPETENCY_STATUS[competency.status] ?? competency.status}
							</p>
						</div>
						<p class="comp-detail">
							{competency.capabilities_covered_this_term} de {competency.capabilities_total}
							capacidades con criterio
						</p>
						{#if competency.status !== 'planificada'}
							<p class="comp-detail">{termsWorkedText(list(competency.terms_worked))}</p>
						{/if}
					</div>
				{/each}
			</div>
		</div>

		<div class="section">
			{#if experiences.length > 0}
				<p class="eyebrow">Experiencias · {experiences.length}</p>
				<div class="stack">
					{#each experiences as experience (experience.id)}
						{@const coverage = coverageOf(experience)}
						<div class="card exp">
							<div class="row exp-head">
								<p class="grow exp-title">{experience.title}</p>
								<p class="exp-status">
									{EXPERIENCE_STATUS[experience.status] ?? experience.status}
								</p>
							</div>
							<p class="meta">
								{fmtRange(experience.starts_on, experience.ends_on)} · {experience.class_dates}
								clases
							</p>
							<p class="exp-comps">
								{list(experience.competencies).map((competency) => competency.name).join(' · ')}
							</p>
							<p class="exp-coverage">
								{coverage.withCriteria} de {coverage.total} capacidades con criterio
							</p>
						</div>
					{/each}
				</div>
			{:else}
				<div class="card empty-card">
					<div class="row empty-row">
						<span class="icon-tile"><Icon name="calendar" size={18} /></span>
						<span class="grow">
							<p class="empty-title">Aún no hay experiencias en este trimestre</p>
							<p class="empty-text">
								Cuéntale a Mawta tu idea: detecta las competencias y arma la propuesta con
								criterios, evidencias y sesiones.
							</p>
						</span>
					</div>
				</div>
			{/if}

			<a
				class="btn-block btn-primary pressable create"
				href={`/class/${courseId}/plan/new`}
				onclick={hapticTap}
			>
				<Icon name="plus" size={16} /> Crear experiencia
			</a>
		</div>
	{:else if loadError}
		<p class="empty">
			No se pudo cargar…
			<button class="pill-light pressable" onclick={load}>Reintentar</button>
		</p>
	{/if}
</div>

<style>
	.screen-sub {
		margin: 10px 0 0;
	}

	.section {
		margin-top: var(--space-xl);
	}

	/* ---- the term as weeks ---- */

	.timeline {
		--cols: 1;
	}

	.tl-head,
	.tl-track,
	.tl-marks {
		display: grid;
		grid-template-columns: repeat(var(--cols), minmax(0, 1fr));
		gap: 3px;
	}

	.tl-head span {
		text-align: center;
		font-family: var(--font-mono);
		font-size: 10px;
		color: var(--text-muted);
	}

	.tl-track {
		margin-top: 6px;
	}

	.tl-week {
		grid-row: 1;
		height: 44px;
		border-radius: var(--radius);
		background: var(--aurora-tint);
	}

	/* What you planned carries the action gradient; the weeks it does not cover
	   stay tinted and quiet — an empty stretch is just empty. */
	.tl-block {
		grid-row: 1;
		height: 44px;
		border-radius: var(--radius);
		background: var(--gradient-action);
		color: var(--on-primary);
		font-size: 11px;
		font-weight: 700;
		line-height: 1.25;
		padding: 6px 7px;
		overflow: hidden;
		z-index: 1;
	}

	.tl-block small {
		display: block;
		margin-top: 2px;
		font-family: var(--font-mono);
		font-size: 9px;
		font-weight: 500;
		opacity: 0.85;
	}

	/* The school's file, drawn as a quiet stripe over the weeks it takes. */
	.tl-off {
		grid-row: 1;
		height: 44px;
		border-radius: var(--radius);
		background: repeating-linear-gradient(
			135deg,
			var(--surface-1) 0 5px,
			var(--aurora-tint) 5px 10px
		);
		color: var(--text-muted);
		font-family: var(--font-mono);
		font-size: 9px;
		display: flex;
		align-items: center;
		justify-content: center;
		overflow: hidden;
		text-align: center;
	}

	.tl-marks {
		margin-top: 4px;
		height: 8px;
	}

	.tl-dot {
		justify-self: center;
		width: 6px;
		height: 6px;
		border-radius: 50%;
		background: var(--text-faint);
	}

	.legend {
		display: flex;
		gap: 14px;
		margin-top: 10px;
		font-size: 11px;
		color: var(--text-muted);
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
		background: var(--gradient-action);
	}

	.sw-off {
		background: repeating-linear-gradient(
			135deg,
			var(--surface-1) 0 3px,
			var(--aurora-tint) 3px 6px
		);
		border: 0.5px solid var(--border);
	}

	.sw-dot {
		width: 6px;
		height: 6px;
		border-radius: 50%;
		background: var(--text-faint);
	}

	/* ---- competencias este trimestre ---- */

	.label-row {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--space-sm);
		margin-bottom: var(--space-xs);
	}

	.label-row .eyebrow {
		margin: 0;
	}

	.comp-row {
		padding: var(--space-sm) 0;
	}

	.comp-row + .comp-row {
		border-top: 0.5px solid var(--hair);
	}

	.row.comp-head {
		justify-content: space-between;
		gap: var(--space-sm);
	}

	.comp-name {
		margin: 0;
		font-size: 13px;
		font-weight: 700;
		line-height: 1.35;
	}

	/* Status is written as text, never a chip. */
	.comp-status {
		margin: 0;
		flex-shrink: 0;
		font-size: 12px;
		font-weight: 600;
		color: var(--text-secondary);
	}

	.comp-detail {
		margin: 3px 0 0;
		font-size: 12px;
		line-height: 1.4;
		color: var(--text-muted);
	}

	/* ---- experiencias ---- */

	.stack {
		display: flex;
		flex-direction: column;
		gap: var(--space-sm);
	}

	.exp {
		padding: var(--space-md);
	}

	.row.exp-head {
		gap: var(--space-sm);
	}

	.exp-title {
		margin: 0;
		font-size: 15px;
		font-weight: 700;
		letter-spacing: -0.01em;
		line-height: 1.3;
	}

	.exp-status {
		margin: 0;
		flex-shrink: 0;
		font-size: 12px;
		font-weight: 600;
		color: var(--text-secondary);
	}

	.exp .meta {
		margin: 4px 0 0;
	}

	.exp-comps {
		margin: 6px 0 0;
		font-size: 12px;
		line-height: 1.4;
		color: var(--text-secondary);
	}

	.exp-coverage {
		margin: 3px 0 0;
		font-size: 12px;
		color: var(--text-muted);
	}

	/* ---- empty state and the one primary action ---- */

	.empty-card {
		padding: var(--space-lg);
	}

	.row.empty-row {
		align-items: flex-start;
	}

	.empty-title {
		margin: 0;
		font-size: 15px;
		font-weight: 700;
		line-height: 1.3;
	}

	.empty-text {
		margin: 6px 0 0;
		font-size: 13px;
		line-height: 1.45;
		color: var(--text-muted);
	}

	.create {
		margin-top: var(--space-md);
	}

	.empty {
		margin: var(--space-lg) 0 0;
		font-size: 13px;
		color: var(--text-muted);
	}
</style>
