<script lang="ts">
	import {
		Action,
		Button,
		EmptyState,
		ErrorNotice,
		Field,
		Icon,
		ItemActions,
		LoadingState,
		Notice,
		PendingDialog,
		ProposalBar,
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
	import type { ExperienceDto, SessionOutlineDto } from '$lib/api/dto';
	import {
		acceptSession,
		deleteSession,
		generateSessions,
		getExperience,
		updateSession,
	} from '$lib/api/endpoints/planning';
	import TopBar from '$lib/components/TopBar.svelte';
	import { hapticTap } from '$lib/haptics';
	import { runSequential } from '$lib/batch';
	import { showError, showToast } from '$lib/toast';

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
	const proposals = $derived(sessions.filter(isProposal));
	let acceptingAll = $state<{ done: number; total: number } | null>(null);
	let pendingOpen = $state(false);
	const loose = $derived(evidences.filter((evidence) => !evidence.session_date));

	function isProposal(session: SessionOutlineDto): boolean {
		return session.proposed_by === 'mawta' && session.accepted_at === null;
	}

	function evidenceName(id: string | null): string {
		if (!id) return '';
		return evidences.find((evidence) => evidence.id === id)?.name ?? '';
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
			showError('No se pudo aceptar la sesión', { onRetry: () => void accept(date) });
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

	// Accepts each proposal in turn; failures are kept for a retry instead of stopping the batch.
	async function acceptAll(items: SessionOutlineDto[] = proposals): Promise<void> {
		hapticTap();
		acceptingAll = { done: 0, total: items.length };
		const result = await runSequential(
			items,
			(session) => acceptSession(experienceId, session.date),
			(done, total) => {
				acceptingAll = { done, total };
			}
		);
		acceptingAll = null;
		await reload();
		if (result.failed.length > 0)
			showError(`No se aceptaron ${result.failed.length} de ${items.length} sesiones`, {
				onRetry: () => void acceptAll(result.failed),
			});
	}

	// "Continuar" asks first when Mawta's proposals are still unreviewed.
	function requestNext(): void {
		if (!editing && proposals.length > 0) pendingOpen = true;
		else next();
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
			<p class="eyebrow">{experience.title} · Paso 3 de 4 · Sesiones</p>
			<h1 class="screen-title">{dates.length} clases</h1>
			<p class="screen-sub">
				{filled} de {dates.length} con sesión · contadas por fecha según tu horario
			</p>

			{#if loose.length > 0 && filled > 0}
				<Notice variant="attention">
					<p>
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
					<ProposalBar
						message="Mawta propuso estas sesiones: acéptalas o edítalas."
						count={proposals.length}
						label="Aceptar propuestas"
						loading={acceptingAll !== null}
						progress={acceptingAll
							? `Aceptando ${acceptingAll.done} de ${acceptingAll.total}…`
							: undefined}
						onaccept={() => void acceptAll()}
					/>
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
									<p class="mw-field__error"><Icon name="alert" size={14} /> {formError}</p>
								{/if}
								<div class="actions row">
									<Action
										variant="main"
										disabled={form.title.trim() === '' || saving}
										onclick={() => void save()}
									>
										<Icon name="check" size={13} /> Guardar
									</Action>
									<Action variant="neutral" onclick={() => (form = null)}>Cancelar</Action>
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
									<ItemActions
										proposal={isProposal(session)}
										onaccept={() => void accept(date)}
										onedit={() => openForm(date)}
										onremove={() => void remove(session)}
									/>
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
				<PendingDialog
					bind:open={pendingOpen}
					count={proposals.length}
					onreview={() => {}}
					oncontinue={next}
				/>
				<Button variant="primary" block onclick={requestNext}>
					{#if editing}Listo{:else}Continuar <Icon name="chevron-right" size={16} />{/if}
				</Button>
			</div>
		{:else if loadError}
			<ErrorNotice message="No se pudo cargar la experiencia." onretry={load} />
		{:else}<LoadingState label="Cargando…" />{/if}
	</div>
</div>

<style>
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

	.later {
		margin-top: var(--mw-space-3);
	}

	.footer-action {
		margin-top: var(--mw-space-6);
	}

	.view :global(.to-summary) {
		margin: 2px 0 6px;
	}
</style>
