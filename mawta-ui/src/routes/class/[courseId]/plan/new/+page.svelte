<script lang="ts">
	import { onMount } from 'svelte';
	import { page } from '$app/state';
	import { goto } from '$app/navigation';
	import { ApiError, list } from '$lib/api/client';
	import type {
		CalendarDto,
		ClassPlanDto,
		CurriculumDto,
		ExperienceProposalBody,
		ExperienceProposalDto,
		GenerationDto,
	} from '$lib/api/dto';
	import {
		createExperience,
		getCalendar,
		getClassCurriculum,
		getClassPlan,
		getGeneration,
		proposeExperience,
	} from '$lib/api/endpoints/planning';
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

	// Weeks are counted from the term's first day, as in "Tu trimestre".
	const weekCount = $derived.by(() => {
		if (!plan) return 1;
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

	const weekOptions = $derived.by(() => {
		const weeks: number[] = [];
		for (let week = 1; week <= weekCount; week++) weeks.push(week);
		return weeks;
	});

	function weekStartISO(week: number): string {
		if (!plan) return '';
		return addDays(plan.term.starts_on, (week - 1) * 7);
	}

	// The review's editable dates: a start week and a length in weeks. The end
	// never passes the term's end.
	let startWeek = $state(1);
	let lengthWeeks = $state(3);

	const maxLength = $derived(Math.min(6, weekCount - startWeek + 1));
	const startsOn = $derived(weekStartISO(startWeek));
	const endsOn = $derived.by(() => {
		if (!plan) return '';
		const end = addDays(weekStartISO(startWeek), lengthWeeks * 7 - 1);
		return end > plan.term.ends_on ? plan.term.ends_on : end;
	});

	function setStartWeek(week: number): void {
		startWeek = week;
		lengthWeeks = Math.min(lengthWeeks, maxLength);
	}

	function setLength(next: number): void {
		lengthWeeks = Math.min(Math.max(next, 1), maxLength);
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

	const sleep = (ms: number): Promise<void> => new Promise((resolve) => setTimeout(resolve, ms));

	// The generation runs in the background: poll about every second until it
	// completes or fails.
	async function poll(generationId: string): Promise<GenerationDto> {
		for (;;) {
			await sleep(1000);
			const generation = await getGeneration(generationId);
			if (generation.status === 'completed' || generation.status === 'failed') return generation;
		}
	}

	function applyProposal(proposal: ExperienceProposalDto): void {
		title = proposal.title;
		situation = proposal.situation_text;
		selected = [...proposal.competency_ids];
		startWeek = weekOf(proposal.starts_on);
		lengthWeeks = Math.max(1, weekOf(proposal.ends_on) - startWeek + 1);
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
			const done = await poll(started.id);
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
			genError = err instanceof ApiError ? err.message : 'No se pudo armar la propuesta.';
		} finally {
			generating = false;
		}
	}

	// ---- "Guardar borrador" ----

	let title = $state('');
	let situation = $state('');
	let saving = $state(false);
	let saveError = $state<{ code: string; message: string } | null>(null);

	// The contract's date problems, with this screen's own Spanish text —
	// shown next to the dates, never as a raw code.
	const DATE_ERRORS: Record<string, string> = {
		experience_overlap: 'Las fechas se cruzan con otra experiencia.',
		outside_term: 'La experiencia debe empezar y terminar dentro del periodo.',
	};

	const saveErrorText = $derived(
		saveError === null ? null : (DATE_ERRORS[saveError.code] ?? saveError.message)
	);

	async function save(): Promise<void> {
		if (saving || !plan) return;
		saving = true;
		saveError = null;
		try {
			const experience = await createExperience(courseId, {
				term_id: plan.term.id,
				title: title.trim(),
				idea_text: ideaText.trim(),
				situation_text: situation.trim(),
				starts_on: startsOn,
				ends_on: endsOn,
				competency_ids: [...selected],
			});
			showToast('Borrador guardado');
			goto(`/class/${courseId}/plan/${experience.id}/criteria`);
		} catch (err) {
			saveError =
				err instanceof ApiError
					? { code: err.code, message: err.message }
					: { code: 'unknown', message: 'No se pudo guardar el borrador.' };
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
				Cuéntalo en una o dos frases. Mawta detecta las competencias y arma la propuesta; luego tú
				la revisas.
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
				<button class="btn-light pressable retry" onclick={() => void generate()}>
					Reintentar
				</button>
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
				<button
					class="btn-block btn-primary pressable primary"
					onclick={() => void generate()}
					disabled={ideaText.trim() === ''}
				>
					✦ Generar con Mawta
				</button>
			{/if}
		{:else if step === 'review'}
			<p class="origin">
				<span class="ai-star">✦</span>
				Mawta la armó a partir de tu idea: “{ideaText}”. Aún no está guardada.
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
					<label class="f-label grow" for="f-situation">Situación</label>
					<button class="link pressable" onclick={() => void generate()} disabled={generating}>
						✦ Sugerir otra
					</button>
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
					<button class="btn-light pressable retry" onclick={() => void generate()}>
						Reintentar
					</button>
				{/if}
			</div>

			<div class="section">
				<div class="row label-row">
					<p class="f-label grow">Competencias</p>
					<button class="link pressable" onclick={() => (step = 'change')}>Cambiar</button>
				</div>
				<p class="comp-sentence">{joinY(selectedNames)}.</p>
			</div>

			<div class="section">
				<p class="f-label">¿Cuándo?</p>
				<div class="row when-row">
					<select
						class="field grow"
						value={startWeek}
						onchange={(event) => setStartWeek(Number(event.currentTarget.value))}
					>
						{#each weekOptions as week (week)}
							<option value={week}>Semana {week} · {fmtDate(weekStartISO(week))}</option>
						{/each}
					</select>
					<div class="stepper">
						<button
							class="pressable"
							onclick={() => setLength(lengthWeeks - 1)}
							disabled={lengthWeeks <= 1}
							aria-label="Menos semanas"
						>
							−
						</button>
						<span><b>{lengthWeeks}</b> sem.</span>
						<button
							class="pressable"
							onclick={() => setLength(lengthWeeks + 1)}
							disabled={lengthWeeks >= maxLength}
							aria-label="Más semanas"
						>
							+
						</button>
					</div>
				</div>
				<p class="f-help">
					<Icon name="calendar" size={12} />
					Semanas {startWeek}–{weekOf(endsOn)} · {rangeClassDates.length} clases ({classDaysText})
				</p>
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
				disabled={saving || selected.length === 0 || title.trim() === '' || situation.trim() === ''}
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

	.stepper {
		display: flex;
		align-items: center;
		gap: 10px;
		flex-shrink: 0;
		font-size: 13px;
		color: var(--text-secondary);
	}

	.stepper button {
		width: 36px;
		height: 36px;
		border-radius: 50%;
		background: var(--aurora-tint);
		color: var(--aurora-deep);
		font-size: 16px;
		font-weight: 700;
	}

	.stepper button:disabled {
		opacity: 0.4;
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
