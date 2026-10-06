<script lang="ts">
	import { onDestroy, onMount } from 'svelte';
	import { page } from '$app/state';
	import { goto } from '$app/navigation';
	import { list } from '$lib/api/client';
	import type {
		CalendarDto,
		ClassPlanDto,
		CurriculumDto,
		ExperienceProposalBody,
		ExperienceProposalDto,
	} from '$lib/api/dto';
	import {
		createExperience,
		getCalendar,
		getClassCurriculum,
		getClassPlan,
		proposeExperience,
	} from '$lib/api/endpoints/planning';
	import { agentUnavailable, GenerationAborted, waitForGeneration } from '$lib/api/generation';
	import { isAgentUnavailable, planningErrorText } from '$lib/api/planningErrors';
	import Icon from '$lib/components/Icon.svelte';
	import TopBar from '$lib/components/TopBar.svelte';
	import { hapticTap } from '$lib/haptics';
	import { showToast } from '$lib/toast';

	const courseId = $derived(page.params.courseId ?? '');

	// ---- load: the plan (term + statuses), the curriculum and the calendar ----

	let ready = $state(false);
	let loadError = $state(false);
	let plan = $state<ClassPlanDto | null>(null);
	let curriculum = $state<CurriculumDto | null>(null);
	let calendar = $state<CalendarDto | null>(null);

	async function load(): Promise<void> {
		ready = false;
		loadError = false;
		try {
			plan = await getClassPlan(courseId);
			curriculum = await getClassCurriculum(courseId);
			calendar = await getCalendar(courseId, plan.term.starts_on, plan.term.ends_on);
			// The competencias that toca this term come pre-marked; the rest stay
			// for Mawta to detect from the idea.
			selected = list(plan.competencies)
				.filter((competency) => competency.status === 'toca')
				.map((competency) => competency.id);
			setStart(startOptions[0] ?? '');
			ready = true;
		} catch {
			loadError = true;
		}
	}

	onMount(load);

	// ---- the two steps on one route ----

	type Step = 'idea' | 'review' | 'change';
	let step = $state<Step>('idea');
	let ideaText = $state('');
	let selected = $state<string[]>([]);

	const competencies = $derived(list(curriculum?.competencies));

	const selectedNames = $derived(
		selected
			.map((id) => competencies.find((competency) => competency.id === id)?.name ?? '')
			.filter((name) => name !== '')
	);

	// "A, B y C" — the competencias as one sentence, never a list of chips.
	function joinY(parts: string[]): string {
		if (parts.length <= 1) return parts[0] ?? '';
		return `${parts.slice(0, -1).join(', ')} y ${parts[parts.length - 1]}`;
	}

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
	const WEEKDAY_SHORT = ['dom', 'lun', 'mar', 'mié', 'jue', 'vie', 'sáb'];

	// "YYYY-MM-DD" → local midnight, so no UTC shift ever moves a class date.
	function fromISO(date: string): Date {
		const [y, m, d] = date.split('-').map(Number);
		return new Date(y ?? 1970, (m ?? 1) - 1, d ?? 1);
	}

	function toISO(date: Date): string {
		const y = String(date.getFullYear()).padStart(4, '0');
		const m = String(date.getMonth() + 1).padStart(2, '0');
		const d = String(date.getDate()).padStart(2, '0');
		return `${y}-${m}-${d}`;
	}

	function addDays(date: string, days: number): string {
		const next = fromISO(date);
		next.setDate(next.getDate() + days);
		return toISO(next);
	}

	// "15 jun"
	function fmtDate(date: string): string {
		const day = fromISO(date);
		return `${day.getDate()} ${MONTHS[day.getMonth()]}`;
	}

	// "lun 15 jun"
	function fmtDay(date: string): string {
		return `${WEEKDAY_SHORT[fromISO(date).getDay()]} ${fmtDate(date)}`;
	}

	// The review's editable dates, by day: the agent fits its proposal to the
	// free days of the term, so the dates are kept exactly as proposed. A day
	// another experience of the class already covers (drafts included) cannot
	// be chosen: the server would reject the overlap.
	let startsOn = $state('');
	let endsOn = $state('');

	const busy = $derived(
		list(plan?.experiences).map((experience) => ({
			from: experience.starts_on,
			to: experience.ends_on,
		}))
	);

	function isBusy(date: string): boolean {
		return busy.some((range) => date >= range.from && date <= range.to);
	}

	const classDates = $derived(list(calendar?.class_dates));

	// Class days on which an experience can start.
	const startOptions = $derived(classDates.filter((date) => !isBusy(date)));

	// The last day an experience starting on `start` can reach: the day before
	// the next experience, or the term's end.
	function limitFrom(start: string): string {
		let limit = plan?.term.ends_on ?? start;
		for (const range of busy) {
			if (range.from > start) {
				const before = addDays(range.from, -1);
				if (before < limit) limit = before;
			}
		}
		return limit;
	}

	// The end choices: class days from the start up to that limit.
	const endOptions = $derived.by(() => {
		if (startsOn === '') return [];
		const limit = limitFrom(startsOn);
		return classDates.filter((date) => date >= startsOn && date <= limit);
	});

	// About three weeks of classes, as far as the free stretch allows.
	function defaultEnd(start: string): string {
		const limit = limitFrom(start);
		const target = addDays(start, 18);
		const fits = classDates.filter((date) => date >= start && date <= limit);
		const upToTarget = fits.filter((date) => date <= target);
		return upToTarget[upToTarget.length - 1] ?? fits[0] ?? start;
	}

	function setStart(start: string): void {
		startsOn = start;
		if (start === '') {
			endsOn = '';
			return;
		}
		if (endsOn < start || endsOn > limitFrom(start)) endsOn = defaultEnd(start);
	}

	// A proposal keeps its own dates (a proposed end may not be a class day; the
	// selects show it anyway). If another tab took the days meanwhile, the
	// server's overlap error explains it on save.
	function setProposalDates(from: string, to: string): void {
		startsOn = from;
		endsOn = to;
	}

	const rangeClassDates = $derived(
		list(calendar?.class_dates).filter((date) => date >= startsOn && date <= endsOn)
	);

	// Which weekdays the class meets, from the calendar itself.
	const classDaysText = $derived.by(() => {
		const days = new Set(rangeClassDates.map((date) => fromISO(date).getDay()));
		return WEEKDAY_SHORT.filter((_, index) => days.has(index)).join(', ');
	});

	// ---- "✦ Generar con Mawta": propose and poll ----

	let generating = $state(false);
	let genError = $state<string | null>(null);

	// Stops waiting for a generation when the screen is left.
	const leaving = new AbortController();
	onDestroy(() => leaving.abort());

	// Where the review's content came from: Mawta's proposal or the teacher.
	let origin = $state<'mawta' | 'teacher'>('mawta');

	function applyProposal(proposal: ExperienceProposalDto): void {
		title = proposal.title;
		situation = proposal.situation_text;
		selected = [...proposal.competency_ids];
		setProposalDates(proposal.starts_on, proposal.ends_on);
		origin = 'mawta';
		step = 'review';
	}

	// "Escribirlo yo": the same review, empty, for the teacher to fill — the way
	// to plan when Mawta is not available or its proposal is not wanted.
	function writeByHand(): void {
		hapticTap();
		genError = null;
		title = '';
		situation = '';
		if (startsOn === '') setStart(startOptions[0] ?? '');
		origin = 'teacher';
		step = 'review';
	}

	// One road for both entries: "✦ Generar con Mawta" from the idea and
	// "Sugerir otra" from the review — the same idea, the current selection.
	async function generate(): Promise<void> {
		if (generating || !plan || ideaText.trim() === '') return;
		generating = true;
		genError = null;
		try {
			const body: ExperienceProposalBody = { term_id: plan.term.id, idea_text: ideaText.trim() };
			if (selected.length > 0) body.competency_ids = [...selected];
			const started = await proposeExperience(courseId, body);
			const done = await waitForGeneration(started, leaving.signal);
			if (done.status === 'failed') {
				genError = done.error ?? 'No se pudo armar la propuesta.';
				return;
			}
			const result = done.result;
			if (result && 'proposal' in result) {
				applyProposal(result.proposal);
			} else {
				genError = 'No se pudo armar la propuesta.';
			}
		} catch (err) {
			if (err instanceof GenerationAborted) return;
			if (isAgentUnavailable(err)) agentUnavailable.set(true);
			genError = planningErrorText(err, 'No se pudo armar la propuesta.');
		} finally {
			generating = false;
		}
	}

	// ---- "Guardar borrador" ----

	let title = $state('');
	let situation = $state('');
	let saving = $state(false);
	// Shown next to the dates (overlap, outside the term, ...), never a raw code.
	let saveErrorText = $state<string | null>(null);

	async function save(): Promise<void> {
		if (saving || !plan) return;
		saving = true;
		saveErrorText = null;
		try {
			const experience = await createExperience(courseId, {
				term_id: plan.term.id,
				title: title.trim(),
				idea_text: ideaText.trim(),
				situation_text: situation.trim() || null,
				starts_on: startsOn,
				ends_on: endsOn,
				competency_ids: [...selected],
			});
			showToast('Borrador guardado');
			goto(`/class/${courseId}/plan/${experience.id}/criteria`);
		} catch (err) {
			saveErrorText = planningErrorText(err, 'No se pudo guardar el borrador.');
		} finally {
			saving = false;
		}
	}
</script>

<svelte:head>
	<title>Nueva experiencia</title>
</svelte:head>

<TopBar back={`/class/${courseId}/plan`} useHistory />

<div class="body">
	{#if ready && plan}
		{#if step === 'idea'}
			<p class="eyebrow">Nueva experiencia de aprendizaje</p>
			<h1 class="screen-title">¿Qué tienes en mente?</h1>
			<p class="helper">
				{#if $agentUnavailable}
					Cuéntalo en una o dos frases; luego escribes la experiencia.
				{:else}
					Cuéntalo en una o dos frases. Mawta detecta las competencias y arma la propuesta; luego tú
					la revisas.
				{/if}
			</p>

			{#if generating}
				<div class="context-card waiting">
					<Icon name="sparkles" size={16} />
					<p class="grow waiting-text">Mawta está armando tu experiencia…</p>
				</div>
			{:else}
				<textarea
					class="field"
					rows="4"
					bind:value={ideaText}
					placeholder="Ej.: que armen y atiendan una tiendita en la feria del aula"></textarea>
			{/if}

			{#if genError !== null}
				<div class="notice">
					<Icon name="alert" size={16} />
					<p class="grow notice-text">{genError}</p>
				</div>
				{#if !$agentUnavailable}
					<button class="btn-light pressable retry" onclick={() => void generate()}>
						Reintentar
					</button>
				{/if}
			{/if}

			<div class="section">
				<p class="eyebrow">Competencias · opcional</p>
				<p class="meta help">
					Si las eliges, Mawta arma la experiencia con ellas; si no, las detecta de tu idea.
				</p>
				<div class="card comp-list">
					{#each competencies as competency (competency.id)}
						<label class="comp-option">
							<input
								type="checkbox"
								bind:group={selected}
								value={competency.id}
								onchange={hapticTap}
							/>
							<span class="grow comp-name">{competency.name}</span>
						</label>
					{/each}
				</div>
			</div>

			{#if !generating}
				{#if $agentUnavailable}
					<button
						class="btn-block btn-primary pressable primary"
						onclick={writeByHand}
						disabled={ideaText.trim() === ''}
					>
						Escribir la experiencia
					</button>
				{:else}
					<button
						class="btn-block btn-primary pressable primary"
						onclick={() => void generate()}
						disabled={ideaText.trim() === ''}
					>
						✦ Generar con Mawta
					</button>
					<button
						class="btn-block btn-light pressable secondary"
						onclick={writeByHand}
						disabled={ideaText.trim() === ''}
					>
						Escribirlo yo
					</button>
				{/if}
			{/if}
		{:else if step === 'review'}
			<p class="origin">
				{#if origin === 'mawta'}
					<span class="ai-star">✦</span>
					Mawta la armó a partir de tu idea: “{ideaText}”. Aún no está guardada.
				{:else}
					Tu idea: “{ideaText}”. Aún no está guardada.
				{/if}
			</p>
			<h1 class="screen-title">Revisa la experiencia</h1>

			<div class="section">
				<label class="f-label" for="f-title">Nombre</label>
				<input
					id="f-title"
					class="field"
					bind:value={title}
					placeholder="Ej.: La tiendita escolar"
				/>
			</div>

			<div class="section">
				<div class="row label-row">
					<label class="f-label grow" for="f-situation">Situación · opcional</label>
					{#if !$agentUnavailable}
						<button class="link pressable" onclick={() => void generate()} disabled={generating}>
							✦ {origin === 'mawta' ? 'Sugerir otra' : 'Sugerir con Mawta'}
						</button>
					{/if}
				</div>
				{#if generating}
					<div class="context-card waiting">
						<Icon name="sparkles" size={16} />
						<p class="grow waiting-text">Mawta está armando otra propuesta…</p>
					</div>
				{:else}
					<textarea id="f-situation" class="field" rows="5" bind:value={situation}></textarea>
				{/if}
				<p class="f-help">El reto real que enfrentarán tus estudiantes. Puedes editarlo.</p>
				{#if genError !== null}
					<div class="notice">
						<Icon name="alert" size={16} />
						<p class="grow notice-text">{genError}</p>
					</div>
					{#if !$agentUnavailable}
						<button class="btn-light pressable retry" onclick={() => void generate()}>
							Reintentar
						</button>
					{/if}
				{/if}
			</div>

			<div class="section">
				<div class="row label-row">
					<p class="f-label grow">Competencias</p>
					<button class="link pressable" onclick={() => (step = 'change')}>Cambiar</button>
				</div>
				<p class="comp-sentence">
					{selectedNames.length > 0 ? `${joinY(selectedNames)}.` : 'Elige al menos una.'}
				</p>
			</div>

			<div class="section">
				<p class="f-label">¿Cuándo?</p>
				{#if startOptions.length === 0}
					<div class="notice">
						<Icon name="alert" size={16} />
						<p class="grow notice-text">
							No quedan días de clase libres en este periodo para una experiencia nueva.
						</p>
					</div>
				{:else}
					<div class="row when-row">
						<label class="grow">
							<span class="f-help">Empieza</span>
							<select
								class="field"
								value={startsOn}
								onchange={(event) => setStart(event.currentTarget.value)}
							>
								{#if startsOn !== '' && !startOptions.includes(startsOn)}
									<option value={startsOn}>{fmtDay(startsOn)}</option>
								{/if}
								{#each startOptions as date (date)}
									<option value={date}>{fmtDay(date)}</option>
								{/each}
							</select>
						</label>
						<label class="grow">
							<span class="f-help">Termina</span>
							<select
								class="field"
								value={endsOn}
								onchange={(event) => (endsOn = event.currentTarget.value)}
							>
								{#if endsOn !== '' && !endOptions.includes(endsOn)}
									<option value={endsOn}>{fmtDay(endsOn)}</option>
								{/if}
								{#each endOptions as date (date)}
									<option value={date}>{fmtDay(date)}</option>
								{/each}
							</select>
						</label>
					</div>
					<p class="f-help">
						<Icon name="calendar" size={12} />
						{rangeClassDates.length} clases{classDaysText ? ` (${classDaysText})` : ''} · los días de
						otras experiencias no aparecen
					</p>
				{/if}
				{#if saveErrorText !== null}
					<div class="notice">
						<Icon name="alert" size={16} />
						<p class="grow notice-text">{saveErrorText}</p>
					</div>
				{/if}
			</div>

			<button
				class="btn-block btn-primary pressable primary"
				onclick={() => void save()}
				disabled={saving ||
					selected.length === 0 ||
					title.trim() === '' ||
					startsOn === '' ||
					endsOn === ''}
			>
				Guardar borrador
			</button>
		{:else if step === 'change'}
			<p class="eyebrow">Nueva experiencia de aprendizaje</p>
			<h1 class="screen-title">Competencias</h1>
			<p class="helper">Elige con qué competencias se arma la experiencia.</p>

			<div class="card comp-list">
				{#each competencies as competency (competency.id)}
					<label class="comp-option">
						<input
							type="checkbox"
							bind:group={selected}
							value={competency.id}
							onchange={hapticTap}
						/>
						<span class="grow comp-name">{competency.name}</span>
					</label>
				{/each}
			</div>

			<button
				class="btn-block btn-primary pressable primary"
				onclick={() => (step = 'review')}
				disabled={selected.length === 0}
			>
				Continuar
			</button>
		{/if}
	{:else if loadError}
		<p class="empty">
			No se pudo cargar…
			<button class="pill-light pressable" onclick={load}>Reintentar</button>
		</p>
	{/if}
</div>

<style>
	.helper {
		margin: 14px 0 10px;
		font-size: 14px;
		line-height: 1.45;
		color: var(--text-secondary);
	}

	.section {
		margin-top: 20px;
	}

	/* Editable things look like labelled form fields. */
	.f-label {
		margin: 0 0 6px;
		font-size: 12px;
		font-weight: 700;
		color: var(--text-secondary);
	}

	.field {
		width: 100%;
		padding: 12px 14px;
		border-radius: 12px;
		border: 1px solid var(--border);
		background: var(--surface-2);
		font-family: inherit;
		font-size: 14px;
		color: var(--text-primary);
		box-sizing: border-box;
	}

	.field:focus {
		outline: none;
		border-color: var(--aurora-deep);
	}

	textarea.field {
		resize: vertical;
		line-height: 1.45;
	}

	.f-help {
		display: flex;
		align-items: center;
		gap: 6px;
		margin: 6px 0 0;
		font-size: 12px;
		line-height: 1.4;
		color: var(--text-muted);
	}

	/* The origin line: the only place the review says Mawta's name. */
	.origin {
		margin: 0 0 14px;
		font-size: 12px;
		line-height: 1.45;
		color: var(--text-muted);
	}

	.ai-star {
		color: var(--text-accent);
	}

	.label-row {
		gap: var(--space-sm);
		align-items: baseline;
	}

	.link {
		border: none;
		padding: 0;
		font-family: inherit;
		font-size: 13px;
		font-weight: 600;
		color: var(--aurora-deep);
		text-decoration: underline;
	}

	.link:disabled {
		opacity: 0.5;
	}

	.comp-list {
		padding: 4px 14px;
	}

	.comp-option {
		display: flex;
		align-items: flex-start;
		gap: 10px;
		padding: 10px 0;
		cursor: pointer;
	}

	.comp-option + .comp-option {
		border-top: 0.5px solid var(--hair);
	}

	.comp-option input {
		width: 18px;
		height: 18px;
		margin: 1px 0 0;
		flex-shrink: 0;
		accent-color: var(--aurora-deep);
	}

	.comp-name {
		font-size: 13px;
		line-height: 1.4;
	}

	.comp-sentence {
		margin: 0;
		font-size: 14px;
		line-height: 1.45;
		color: var(--text-primary);
	}

	.when-row {
		gap: 10px;
	}

	.waiting {
		display: flex;
		align-items: center;
		gap: 10px;
		color: var(--text-accent);
	}

	.waiting-text {
		margin: 0;
		font-size: 13px;
		color: var(--text-secondary);
	}

	.notice {
		display: flex;
		align-items: flex-start;
		gap: var(--space-sm);
		background: var(--bg-danger);
		border-radius: var(--radius);
		padding: var(--space-sm) var(--space-md);
		margin-top: var(--space-md);
		color: var(--text-danger);
	}

	.notice-text {
		margin: 0;
		font-size: 13px;
		color: var(--text-primary);
	}

	.retry {
		margin-top: var(--space-sm);
	}

	.secondary {
		margin-top: 8px;
	}

	.primary {
		margin-top: var(--space-xl);
	}

	.help {
		margin: -4px 0 6px;
	}

	.empty {
		margin: var(--space-lg) 0 0;
		font-size: 13px;
		color: var(--text-muted);
	}
</style>
