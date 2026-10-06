<script lang="ts">
	import {
		Action,
		Button,
		Card,
		Checkbox,
		Context,
		Field,
		Icon,
		LoadingState,
		Notice,
	} from '$lib/design-system';
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
<div class="view">
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
						Cuéntalo en una o dos frases. Mawta detecta las competencias y arma la propuesta; luego
						tú la revisas.
					{/if}
				</p>

				{#if generating}
					<Context>
						<Icon name="sparkles" size={16} />
						<p class="grow waiting-text">Mawta está armando tu experiencia…</p>
					</Context>
				{:else}
					<Field
						kind="textarea"
						label="Tu idea"
						rows={4}
						bind:value={ideaText}
						placeholder="Ej.: que armen y atiendan una tiendita en la feria del aula"
					/>
				{/if}

				{#if genError !== null}
					<Notice variant="attention">
						<p class="grow notice-text">{genError}</p>
					</Notice>
					{#if !$agentUnavailable}
						<Button variant="secondary" class="retry" onclick={() => void generate()}>
							Reintentar
						</Button>
					{/if}
				{/if}

				<div class="section">
					<p class="eyebrow">Competencias · opcional</p>
					<p class="meta help">
						Si las eliges, Mawta arma la experiencia con ellas; si no, las detecta de tu idea.
					</p>
					<Card>
						{#each competencies as competency (competency.id)}
							<Checkbox
								checked={selected.includes(competency.id)}
								onchange={(event) => {
									selected = event.currentTarget.checked
										? [...selected, competency.id]
										: selected.filter((id) => id !== competency.id);
									hapticTap();
								}}
							>
								<span class="grow comp-name">{competency.name}</span>
							</Checkbox>
						{/each}
					</Card>
				</div>

				{#if !generating}
					{#if $agentUnavailable}
						<Button
							variant="primary"
							block
							class="primary"
							onclick={writeByHand}
							disabled={ideaText.trim() === ''}
						>
							Escribir la experiencia
						</Button>
					{:else}
						<Button
							variant="primary"
							block
							class="primary"
							onclick={() => void generate()}
							disabled={ideaText.trim() === ''}
						>
							✦ Generar con Mawta
						</Button>
						<Button
							variant="secondary"
							block
							class="secondary"
							onclick={writeByHand}
							disabled={ideaText.trim() === ''}
						>
							Escribirlo yo
						</Button>
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
					<Field
						label="Nombre"
						id="f-title"
						bind:value={title}
						placeholder="Ej.: La tiendita escolar"
					/>
				</div>

				<div class="section">
					{#if generating}
						<Context>
							<Icon name="sparkles" size={16} />
							<p class="grow waiting-text">Mawta está armando otra propuesta…</p>
						</Context>
					{:else}
						<Field
							kind="textarea"
							label="Situación · opcional"
							id="f-situation"
							rows={5}
							bind:value={situation}
							help="El reto real que enfrentarán tus estudiantes. Puedes editarlo."
						>
							{#snippet labelAction()}{#if !$agentUnavailable}<Action
										variant="link"
										onclick={() => void generate()}
										disabled={generating}
										>✦ {origin === 'mawta' ? 'Sugerir otra' : 'Sugerir con Mawta'}</Action
									>{/if}{/snippet}
						</Field>
					{/if}

					{#if genError !== null}
						<Notice variant="attention">
							<p class="grow notice-text">{genError}</p>
						</Notice>
						{#if !$agentUnavailable}
							<Button variant="secondary" class="retry" onclick={() => void generate()}>
								Reintentar
							</Button>
						{/if}
					{/if}
				</div>

				<div class="section">
					<div class="row label-row">
						<p class="f-label grow">Competencias</p>
						<Action variant="link" onclick={() => (step = 'change')}>Cambiar</Action>
					</div>
					<p class="comp-sentence">
						{selectedNames.length > 0 ? `${joinY(selectedNames)}.` : 'Elige al menos una.'}
					</p>
				</div>

				<div class="section">
					<p class="f-label">¿Cuándo?</p>
					{#if startOptions.length === 0}
						<Notice variant="attention">
							<p class="grow notice-text">
								No quedan días de clase libres en este periodo para una experiencia nueva.
							</p>
						</Notice>
					{:else}
						<div class="row when-row">
							<Field
								kind="select"
								label="Empieza"
								value={startsOn}
								onchange={(event) => setStart(event.currentTarget.value)}
							>
								{#if startsOn !== '' && !startOptions.includes(startsOn)}
									<option value={startsOn}>{fmtDay(startsOn)}</option>
								{/if}
								{#each startOptions as date (date)}
									<option value={date}>{fmtDay(date)}</option>
								{/each}
							</Field>
							<Field
								kind="select"
								label="Termina"
								value={endsOn}
								onchange={(event) => (endsOn = event.currentTarget.value)}
							>
								{#if endsOn !== '' && !endOptions.includes(endsOn)}
									<option value={endsOn}>{fmtDay(endsOn)}</option>
								{/if}
								{#each endOptions as date (date)}
									<option value={date}>{fmtDay(date)}</option>
								{/each}
							</Field>
						</div>
						<p class="f-help">
							<Icon name="calendar" size={12} />
							{rangeClassDates.length} clases{classDaysText ? ` (${classDaysText})` : ''} · los días de
							otras experiencias no aparecen
						</p>
					{/if}
					{#if saveErrorText !== null}
						<Notice variant="attention">
							<p class="grow notice-text">{saveErrorText}</p>
						</Notice>
					{/if}
				</div>

				<Button
					variant="primary"
					block
					class="primary"
					onclick={() => void save()}
					disabled={saving ||
						selected.length === 0 ||
						title.trim() === '' ||
						startsOn === '' ||
						endsOn === ''}
				>
					Guardar borrador
				</Button>
			{:else if step === 'change'}
				<p class="eyebrow">Nueva experiencia de aprendizaje</p>
				<h1 class="screen-title">Competencias</h1>
				<p class="helper">Elige con qué competencias se arma la experiencia.</p>

				<Card>
					{#each competencies as competency (competency.id)}
						<Checkbox
							checked={selected.includes(competency.id)}
							onchange={(event) => {
								selected = event.currentTarget.checked
									? [...selected, competency.id]
									: selected.filter((id) => id !== competency.id);
								hapticTap();
							}}
						>
							<span class="grow comp-name">{competency.name}</span>
						</Checkbox>
					{/each}
				</Card>

				<Button
					variant="primary"
					block
					class="primary"
					onclick={() => (step = 'review')}
					disabled={selected.length === 0}
				>
					Continuar
				</Button>
			{/if}
		{:else if loadError}
			<p class="empty">
				No se pudo cargar…
				<Button variant="secondary" onclick={load}>Reintentar</Button>
			</p>
		{:else}<LoadingState label="Cargando…" />{/if}
	</div>
</div>

<style>
	.helper {
		margin: 14px 0 10px;
		font-size: var(--mw-type-body-size);
		line-height: 1.45;
		color: var(--mw-ink-secondary);
	}

	.section {
		margin-top: 20px;
	}

	.f-label {
		margin: 0 0 6px;
		font-size: var(--mw-type-caption-size);
		font-weight: 700;
		color: var(--mw-ink-secondary);
	}
	.view :global(.field) {
		width: 100%;
	}

	.f-help {
		display: flex;
		align-items: center;
		gap: 6px;
		margin: 6px 0 0;
		font-size: var(--mw-type-caption-size);
		line-height: 1.4;
		color: var(--mw-ink-muted);
	}

	.origin {
		margin: 0 0 14px;
		font-size: var(--mw-type-caption-size);
		line-height: 1.45;
		color: var(--mw-ink-muted);
	}

	.ai-star {
		color: var(--mw-accent);
	}

	.label-row {
		gap: var(--mw-space-2);
		align-items: baseline;
	}

	.comp-name {
		font-size: var(--mw-type-small-size);
		line-height: 1.4;
	}

	.comp-sentence {
		margin: 0;
		font-size: var(--mw-type-body-size);
		line-height: 1.45;
		color: var(--mw-ink);
	}

	.when-row {
		gap: 10px;
	}

	.waiting-text {
		margin: 0;
		font-size: var(--mw-type-small-size);
		color: var(--mw-ink-secondary);
	}

	.notice-text {
		margin: 0;
		font-size: var(--mw-type-small-size);
		color: var(--mw-ink);
	}
	.view :global(.retry) {
		margin-top: var(--mw-space-2);
	}
	.view :global(.secondary) {
		margin-top: 8px;
	}
	.view :global(.primary) {
		margin-top: var(--mw-space-6);
	}

	.help {
		margin: -4px 0 6px;
	}

	.empty {
		margin: var(--mw-space-4) 0 0;
		font-size: var(--mw-type-small-size);
		color: var(--mw-ink-muted);
	}
</style>
