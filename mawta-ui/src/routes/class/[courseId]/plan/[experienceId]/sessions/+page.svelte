<script lang="ts">
	import {
		Action,
		Button,
		EmptyState,
		Field,
		Icon,
		LoadingState,
		Notice,
		SessionRow,
	} from '$lib/design-system';
	// The sessions step: a light outline, one row per class date of the
	// experience. Every date starts without a session; the teacher creates,
	// edits, removes or accepts them, and places an evidencia in a date.
	// "✦ Generar esquema con Mawta" only fills the dates still empty.
	import { onDestroy, onMount } from 'svelte';
	import { page } from '$app/state';
	import { goto } from '$app/navigation';
	import { list } from '$lib/api/client';
	import { agentUnavailable, GenerationAborted, waitForGeneration } from '$lib/api/generation';
	import { isAgentUnavailable, planningErrorText } from '$lib/api/planningErrors';
	import type { ExperienceDto, GenerationDto, SessionOutlineDto } from '$lib/api/dto';
	import {
		acceptSession,
		deleteSession,
		generateSessions,
		getExperience,
		updateSession,
	} from '$lib/api/endpoints/planning';
	import TopBar from '$lib/components/TopBar.svelte';
	import { hapticTap } from '$lib/haptics';
	import { showToast } from '$lib/toast';

	const courseId = $derived(page.params.courseId ?? '');
	const experienceId = $derived(page.params.experienceId ?? '');

	let ready = $state(false);
	let loadError = $state(false);
	let experience = $state<ExperienceDto | null>(null);
	// Opened from the summary (or already planned): the step is a leaf of the
	// hub and "Listo" returns there, instead of walking on to the next step.
	const editing = $derived(
		page.url.searchParams.get('from') === 'summary' || experience?.status === 'planificada'
	);
	const summaryHref = $derived(`/class/${courseId}/plan/${experienceId}/summary`);

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
		return planningErrorText(error, 'No se pudo guardar la sesión. Inténtalo de nuevo.');
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
				durationMs: 7000,
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

	// Stops waiting for a generation when the screen is left.
	const leaving = new AbortController();
	onDestroy(() => leaving.abort());

	async function generate(): Promise<void> {
		if (generating) return;
		hapticTap();
		generating = true;
		form = null;
		try {
			const started = await generateSessions(experienceId);
			const done = await waitForGeneration(started, leaving.signal);
			if (done.status === 'failed') {
				showToast(done.error ?? 'Mawta no pudo proponer sesiones esta vez');
			} else {
				await reload();
			}
		} catch (error) {
			if (error instanceof GenerationAborted) return;
			if (isAgentUnavailable(error)) agentUnavailable.set(true);
			showToast(planningErrorText(error, 'No se pudo generar con Mawta'));
		} finally {
			generating = false;
		}
	}

	function next(): void {
		hapticTap();
		void goto(editing ? summaryHref : `/class/${courseId}/plan/${experienceId}/summary`, {
			replaceState: true,
		});
	}
</script>

<svelte:head>
	<title>Sesiones</title>
</svelte:head>
<div class="view">
	<TopBar back={editing ? summaryHref : `/class/${courseId}/plan/${experienceId}/evidences`} />

	<div class="body">
		{#if ready && experience}
			<p class="eyebrow">{experience.title} · Sesiones</p>
			<h1 class="screen-title title">{dates.length} clases</h1>
			<p class="screen-sub">
				{filled} de {dates.length} con sesión · contadas por fecha según tu horario
			</p>

			{#if loose.length > 0 && filled > 0}
				<Notice variant="attention">
					<p class="notice-text">
						Evidencias sin sesión: {loose.map((evidence) => evidence.name).join(', ')}. Edita una
						sesión para ubicarlas.
					</p>
				</Notice>
			{/if}

			{#if empty > 0 && !$agentUnavailable}
				<Button
					variant="secondary"
					block
					class="gen"
					disabled={generating}
					onclick={() => void generate()}
				>
					<Icon name="sparkles" size={15} />
					{filled > 0 ? 'Generar las sesiones que faltan' : 'Generar esquema con Mawta'}
				</Button>
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
						{#snippet sessionEditor()}{#if form}<Field
									label="Título de la sesión"
									placeholder="Título de la sesión"
									bind:value={form.title}
								/>
								<Field
									label="Temas"
									placeholder="Temas (p. ej., resta con canjes)"
									bind:value={form.topics}
									class="spaced"
								/>
								<Field
									kind="select"
									label="Evidencia de la sesión"
									bind:value={form.evidenceId}
									class="spaced"
								>
									<option value="">Sin evidencia en esta sesión</option>
									{#each evidences as evidence (evidence.id)}
										<option value={evidence.id}>Evidencia: {evidence.name}</option>
									{/each}
								</Field>
								{#if formError}
									<p class="form-error"><Icon name="alert" size={14} /> {formError}</p>
								{/if}
								<div class="actions row">
									<Action
										variant="main"
										disabled={form.title.trim() === '' || saving}
										onclick={() => void save()}
									>
										<Icon name="check" size={13} /> Guardar
									</Action>
									<Action variant="remove" onclick={() => (form = null)}>Cancelar</Action>
								</div>
							{/if}{/snippet}
						<SessionRow
							{date}
							title={session?.title ?? 'Sin sesión'}
							topics={session?.topics ?? undefined}
							evidence={session && evidenceName(session.planned_evidence_id)
								? { name: evidenceName(session.planned_evidence_id) }
								: undefined}
							editor={form?.date === date ? sessionEditor : undefined}
						>
							{#snippet actions()}{#if session}
									{#if isProposal(session)}<Action
											variant="main"
											icon="check"
											onclick={() => void accept(date)}>Aceptar</Action
										>{/if}
									<Action variant="link" onclick={() => openForm(date)}>Editar</Action>
									<Action variant="remove" icon="trash" onclick={() => void remove(session)}
										>Quitar</Action
									>
								{:else}<Action variant="link" icon="plus" onclick={() => openForm(date)}
										>Crear</Action
									>{/if}{/snippet}
						</SessionRow>
					{/each}
				</div>
				{#if dates.length === 0}
					<EmptyState title="Esta experiencia no tiene fechas de clase." />
				{/if}
			</div>

			<p class="meta later">Antes de cada clase, Mawta podrá preparar el detalle de la sesión.</p>

			<div class="footer-action">
				<Button variant="primary" block onclick={next}>
					{#if editing}Listo{:else}Continuar <Icon name="chevron-right" size={16} />{/if}
				</Button>
			</div>
		{:else if loadError}
			<p class="empty">
				No se pudo cargar la experiencia.
				<Button variant="secondary" onclick={load}>Reintentar</Button>
			</p>
		{:else}<LoadingState label="Cargando…" />{/if}
	</div>
</div>

<style>
	.title {
		font-size: var(--mw-type-title-size);
	}
	.view :global(.gen) {
		margin-top: var(--mw-space-3);
	}

	.gen-help {
		margin: 6px 0 0;
		text-align: center;
	}

	.section {
		margin-top: var(--mw-space-4);
	}

	.help {
		margin: 0 0 6px;
	}

	.sessions {
		border-top: 1px solid var(--mw-line);
	}

	.actions {
		gap: 8px;
		margin-top: 8px;
		flex-wrap: wrap;
	}
	.view :global(.field) {
		width: 100%;
	}
	.view :global(.field):global(.spaced) {
		margin-top: 6px;
	}

	.form-error {
		display: flex;
		align-items: center;
		gap: 6px;
		margin: 8px 0 0;
		font-size: var(--mw-type-caption-size);
		color: var(--mw-ink);
	}

	.notice-text {
		margin: 0;
		font-size: var(--mw-type-small-size);
		line-height: 1.4;
	}

	.later {
		margin-top: var(--mw-space-3);
	}

	.footer-action {
		margin-top: var(--mw-space-6);
	}

	.empty {
		margin: var(--mw-space-4) 0 0;
		font-size: var(--mw-type-small-size);
		color: var(--mw-ink-muted);
	}
	.view :global(.to-summary) {
		margin: 2px 0 6px;
	}
</style>
