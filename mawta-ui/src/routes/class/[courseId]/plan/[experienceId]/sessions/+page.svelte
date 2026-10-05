<script lang="ts">
	// The sessions step: a light outline, one row per class date of the
	// experience. Every date starts without a session; the teacher creates,
	// edits, removes or accepts them, and places an evidencia in a date.
	// "✦ Generar esquema con Mawta" only fills the dates still empty.
	import { onMount } from 'svelte';
	import { page } from '$app/state';
	import { goto } from '$app/navigation';
	import { ApiError, list } from '$lib/api/client';
	import type { ExperienceDto, GenerationDto, SessionOutlineDto } from '$lib/api/dto';
	import {
		acceptSession,
		deleteSession,
		generateSessions,
		getExperience,
		getGeneration,
		updateSession,
	} from '$lib/api/endpoints/planning';
	import Icon from '$lib/components/Icon.svelte';
	import TopBar from '$lib/components/TopBar.svelte';
	import { hapticTap } from '$lib/haptics';
	import { showToast } from '$lib/toast';

	const courseId = $derived(page.params.courseId ?? '');
	const experienceId = $derived(page.params.experienceId ?? '');

	let ready = $state(false);
	let loadError = $state(false);
	let experience = $state<ExperienceDto | null>(null);

	async function load(): Promise<void> {
		ready = false;
		loadError = false;
		try {
			experience = await getExperience(experienceId);
			ready = true;
		} catch {
			loadError = true;
		}
	}

	async function reload(): Promise<void> {
		try {
			experience = await getExperience(experienceId);
		} catch {
			showToast('No se pudo actualizar la experiencia');
		}
	}

	onMount(load);

	const dates = $derived(list(experience?.class_dates));
	const sessions = $derived(list(experience?.sessions));
	const evidences = $derived(list(experience?.evidences));
	const byDate = $derived(new Map(sessions.map((session) => [session.date, session])));
	const filled = $derived(dates.filter((date) => byDate.has(date)).length);
	const empty = $derived(dates.length - filled);
	const pending = $derived(sessions.some(isProposal));
	const loose = $derived(evidences.filter((evidence) => !evidence.session_date));

	function isProposal(session: SessionOutlineDto): boolean {
		return session.proposed_by === 'mawta' && session.accepted_at === null;
	}

	function evidenceName(id: string | null): string {
		if (!id) return '';
		return evidences.find((evidence) => evidence.id === id)?.name ?? '';
	}

	// "Mar 16 jun"
	const WEEKDAYS = ['Dom', 'Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb'];
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

	function fromISO(date: string): Date {
		const [y, m, d] = date.split('-').map(Number);
		return new Date(y ?? 1970, (m ?? 1) - 1, d ?? 1);
	}

	function fmtDate(date: string): string {
		const day = fromISO(date);
		return `${WEEKDAYS[day.getDay()]} ${day.getDate()} ${MONTHS[day.getMonth()]}`;
	}

	// ---- create and edit one date's session ----

	type SessionForm = { date: string; title: string; topics: string; evidenceId: string };

	let form = $state<SessionForm | null>(null);
	let saving = $state(false);
	let formError = $state<string | null>(null);

	function openForm(date: string): void {
		hapticTap();
		formError = null;
		const session = byDate.get(date);
		form = {
			date,
			title: session?.title ?? '',
			topics: session?.topics ?? '',
			evidenceId: session?.planned_evidence_id ?? '',
		};
	}

	function errorText(error: unknown): string {
		if (error instanceof ApiError && error.code === 'date_not_in_experience') {
			return 'Esa fecha no es un día de clase de esta experiencia.';
		}
		return 'No se pudo guardar la sesión. Inténtalo de nuevo.';
	}

	async function save(): Promise<void> {
		if (!form || form.title.trim() === '' || saving) return;
		saving = true;
		formError = null;
		try {
			await updateSession(experienceId, form.date, {
				title: form.title.trim(),
				topics: form.topics.trim() || null,
				planned_evidence_id: form.evidenceId || null,
			});
			form = null;
			await reload();
		} catch (error) {
			formError = errorText(error);
		} finally {
			saving = false;
		}
	}

	async function accept(date: string): Promise<void> {
		hapticTap();
		try {
			await acceptSession(experienceId, date);
			await reload();
		} catch {
			showToast('No se pudo aceptar la sesión');
		}
	}

	// No confirmation: "Deshacer" puts the same session back on its date.
	async function remove(session: SessionOutlineDto): Promise<void> {
		hapticTap();
		const copy = { ...session };
		try {
			await deleteSession(experienceId, session.date);
			if (form?.date === session.date) form = null;
			await reload();
			showToast('Sesión quitada', {
				onUndo: () => void restore(copy),
				undoLabel: 'Deshacer',
				durationMs: 4000,
			});
		} catch {
			showToast('No se pudo quitar la sesión');
		}
	}

	async function restore(session: SessionOutlineDto): Promise<void> {
		try {
			await updateSession(experienceId, session.date, {
				title: session.title,
				topics: session.topics,
				planned_evidence_id: session.planned_evidence_id,
			});
			await reload();
		} catch {
			showToast('No se pudo restaurar la sesión');
		}
	}

	// ---- "✦ Generar esquema con Mawta": only the empty dates ----

	let generating = $state(false);

	const sleep = (ms: number): Promise<void> => new Promise((resolve) => setTimeout(resolve, ms));

	async function poll(generationId: string): Promise<GenerationDto> {
		for (;;) {
			await sleep(1000);
			const generation = await getGeneration(generationId);
			if (generation.status === 'completed' || generation.status === 'failed') return generation;
		}
	}

	async function generate(): Promise<void> {
		if (generating) return;
		hapticTap();
		generating = true;
		form = null;
		try {
			const started = await generateSessions(experienceId);
			const done = await poll(started.id);
			if (done.status === 'failed') {
				showToast(done.error ?? 'Mawta no pudo proponer sesiones esta vez');
			} else {
				await reload();
			}
		} catch {
			showToast('No se pudo generar con Mawta');
		} finally {
			generating = false;
		}
	}

	function next(): void {
		hapticTap();
		void goto(`/class/${courseId}/plan/${experienceId}/summary`);
	}
</script>

<svelte:head>
	<title>Sesiones</title>
</svelte:head>

<TopBar back={`/class/${courseId}/plan/${experienceId}/evidences`} useHistory />

<div class="body">
	{#if ready && experience}
		<p class="eyebrow">{experience.title} · Sesiones</p>
		<h1 class="screen-title title">{dates.length} clases</h1>
		<p class="screen-sub">
			{filled} de {dates.length} con sesión · contadas por fecha según tu horario
		</p>

		{#if loose.length > 0 && filled > 0}
			<div class="notice">
				<Icon name="alert" size={16} />
				<p class="notice-text">
					Evidencias sin sesión: {loose.map((evidence) => evidence.name).join(', ')}. Edita una
					sesión para ubicarlas.
				</p>
			</div>
		{/if}

		{#if empty > 0}
			<button class="btn-block pressable gen" disabled={generating} onclick={() => void generate()}>
				<Icon name="sparkles" size={15} />
				{filled > 0 ? 'Generar las sesiones que faltan' : 'Generar esquema con Mawta'}
			</button>
			<p class="meta gen-help">
				{generating
					? 'Mawta está armando las sesiones de las fechas vacías…'
					: 'Mawta solo completa las fechas que aún no tienen sesión.'}
			</p>
		{/if}

		<div class="section">
			{#if pending}
				<p class="meta help">Mawta propuso estas sesiones: acéptalas o edítalas.</p>
			{/if}
			<div class="sessions">
				{#each dates as date (date)}
					{@const session = byDate.get(date)}
					<div class="sess row">
						<span class="sess-date">{fmtDate(date)}</span>
						<div class="grow">
							{#if form && form.date === date}
								<input class="field" placeholder="Título de la sesión" bind:value={form.title} />
								<input
									class="field spaced"
									placeholder="Temas (p. ej., resta con canjes)"
									bind:value={form.topics}
								/>
								<select class="field spaced" bind:value={form.evidenceId}>
									<option value="">Sin evidencia en esta sesión</option>
									{#each evidences as evidence (evidence.id)}
										<option value={evidence.id}>Evidencia: {evidence.name}</option>
									{/each}
								</select>
								{#if formError}
									<p class="form-error"><Icon name="alert" size={14} /> {formError}</p>
								{/if}
								<div class="actions row">
									<button
										class="mini go pressable"
										disabled={form.title.trim() === '' || saving}
										onclick={() => void save()}
									>
										<Icon name="check" size={13} /> Guardar
									</button>
									<button class="mini quiet pressable" onclick={() => (form = null)}
										>Cancelar</button
									>
								</div>
							{:else if session}
								<p class="sess-title">{session.title}</p>
								{#if session.topics}
									<p class="meta sess-line">Temas: {session.topics}</p>
								{/if}
								{#if evidenceName(session.planned_evidence_id)}
									<p class="sess-ev">
										<Icon name="clipboard-check" size={14} />
										{evidenceName(session.planned_evidence_id)}
									</p>
								{/if}
								<div class="actions row">
									{#if isProposal(session)}
										<button class="mini go pressable" onclick={() => void accept(date)}>
											<Icon name="check" size={13} /> Aceptar
										</button>
									{/if}
									<button class="mini pressable" onclick={() => openForm(date)}>Editar</button>
									<button class="mini quiet pressable" onclick={() => void remove(session)}>
										<Icon name="trash" size={13} /> Quitar
									</button>
								</div>
							{:else}
								<div class="row empty-slot">
									<span class="meta grow">Sin sesión</span>
									<button class="mini pressable" onclick={() => openForm(date)}>
										<Icon name="plus" size={13} /> Crear
									</button>
								</div>
							{/if}
						</div>
					</div>
				{/each}
			</div>
			{#if dates.length === 0}
				<p class="empty">Esta experiencia no tiene fechas de clase.</p>
			{/if}
		</div>

		<p class="meta later">Antes de cada clase, Mawta podrá preparar el detalle de la sesión.</p>

		<div class="footer-action">
			<button class="btn-block btn-primary pressable" onclick={next}>
				Continuar <Icon name="chevron-right" size={16} />
			</button>
		</div>
	{:else if loadError}
		<p class="empty">
			No se pudo cargar la experiencia.
			<button class="pill-light pressable" onclick={load}>Reintentar</button>
		</p>
	{/if}
</div>

<style>
	.title {
		font-size: 28px;
	}

	.gen {
		margin-top: var(--space-md);
		padding: 12px;
		font-size: 13px;
	}

	.gen:disabled {
		opacity: 0.6;
	}

	.gen-help {
		margin: 6px 0 0;
		text-align: center;
	}

	.section {
		margin-top: var(--space-lg);
	}

	.help {
		margin: 0 0 6px;
	}

	.sessions {
		border-top: 0.5px solid var(--hair);
	}

	.sess {
		align-items: flex-start;
		gap: var(--space-md);
		padding: 12px 0;
		border-bottom: 0.5px solid var(--hair);
	}

	.sess-date {
		flex-shrink: 0;
		width: 72px;
		padding-top: 2px;
		font-family: var(--font-mono);
		font-size: 11px;
		color: var(--text-muted);
	}

	.sess-title {
		margin: 0;
		font-size: 14px;
		font-weight: 600;
		line-height: 1.4;
		color: var(--text-primary);
	}

	.sess-line {
		margin: 2px 0 0;
	}

	.sess-ev {
		display: flex;
		align-items: center;
		gap: 6px;
		margin: 6px 0 0;
		font-size: 12px;
		color: var(--text-secondary);
	}

	.empty-slot {
		align-items: center;
		gap: var(--space-sm);
	}

	.actions {
		gap: 8px;
		margin-top: 8px;
		flex-wrap: wrap;
	}

	.mini {
		display: inline-flex;
		align-items: center;
		gap: 4px;
		padding: 7px 12px;
		border-radius: 999px;
		background: var(--aurora-tint);
		color: var(--aurora-deep);
		font-size: 12px;
		font-weight: 600;
	}

	.mini.go {
		background: var(--gradient-action);
		color: var(--on-primary);
	}

	.mini.quiet {
		background: none;
		color: var(--text-muted);
	}

	.mini:disabled {
		opacity: 0.5;
	}

	.field {
		width: 100%;
		padding: 10px 12px;
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

	.field.spaced {
		margin-top: 6px;
	}

	.form-error {
		display: flex;
		align-items: center;
		gap: 6px;
		margin: 8px 0 0;
		font-size: 12px;
		color: var(--text-primary);
	}

	.notice {
		display: flex;
		align-items: flex-start;
		gap: var(--space-sm);
		background: var(--bg-danger);
		border-radius: var(--radius);
		padding: var(--space-sm) var(--space-md);
		margin-top: var(--space-md);
		color: var(--text-primary);
	}

	.notice-text {
		margin: 0;
		font-size: 13px;
		line-height: 1.4;
	}

	.later {
		margin-top: var(--space-md);
	}

	.footer-action {
		margin-top: var(--space-xl);
	}

	.empty {
		margin: var(--space-lg) 0 0;
		font-size: 13px;
		color: var(--text-muted);
	}
</style>
