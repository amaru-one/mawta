<script lang="ts">
	// "✦ Generar con Mawta" for the conclusión descriptiva of one student in one
	// competencia (mawta-server/docs/api-conclusiones.md).
	//
	// Mawta only proposes. The proposal is shown apart from the teacher's text,
	// with what each sentence rests on, and only "Usar esta propuesta" copies it
	// into the draft — where the teacher edits and saves it as their own. It is
	// never saved, let alone marked final, from here.
	//
	// The level comes first: the conclusion explains the level the teacher
	// asserted, so without one there is nothing to propose.
	import { onDestroy, untrack } from 'svelte';

	import { Button, Field, Icon, Notice } from '$lib/design-system';
	import { ApiError, list } from '$lib/api/client';
	import type {
		ClassStudentDto,
		ConclusionPointDto,
		ConclusionProposalDto,
		ConclusionWarningDto,
		DiscardedVoiceNoteDto,
		GenerationDto,
		InsufficientEvidenceDto,
		NivelLogro,
	} from '$lib/api/dto';
	import {
		generateConclusion,
		getDiscardedVoiceNotes,
		getLatestConclusionGeneration,
	} from '$lib/api/endpoints/competencies';
	import { confirmVoiceNote, reassignVoiceNote } from '$lib/api/endpoints/sessions';
	import { getClassStudents } from '$lib/api/endpoints/students';
	import { agentUnavailable, GenerationAborted, waitForGeneration } from '$lib/api/generation';
	import { isAgentUnavailable } from '$lib/api/planningErrors';
	import { showToast } from '$lib/toast';
	import type { Note } from '$lib/types';
	import VoiceNotePlayer from './VoiceNotePlayer.svelte';

	interface Props {
		classId: string;
		studentId: string;
		studentName: string;
		competencyId: string;
		level: NivelLogro | null;
		// The title of an evidence of this competencia, to show what a sentence
		// rests on.
		evidenceTitle: (assessmentId: string) => string | undefined;
		// The teacher chose to start from the proposal.
		onuse: (body: string, generationId: string) => void;
	}

	let { classId, studentId, studentName, competencyId, level, evidenceTitle, onuse }: Props =
		$props();

	let working = $state(false);
	let generation = $state<GenerationDto | null>(null);
	let thin = $state<InsufficientEvidenceDto | null>(null);
	let discarded = $state<DiscardedVoiceNoteDto[]>([]);
	let roster = $state<ClassStudentDto[]>([]);
	let moveTo = $state<Record<string, string>>({});
	let busyNote = $state('');

	// Leaving the screen or changing competencia stops any wait in flight.
	let leaving = new AbortController();
	onDestroy(() => leaving.abort());

	const proposal = $derived(
		generation?.status === 'completed' ? (generation.result as ConclusionProposalDto) : null
	);
	const warnings = $derived(list(proposal?.warnings));
	const worstCase = $derived(warnings.some((w) => w.code === 'all_voice_notes_discarded'));

	// A new competencia is a new conclusion: forget the previous one and pick up
	// whatever Mawta last proposed for this one.
	$effect(() => {
		const id = competencyId;
		untrack(() => {
			leaving.abort();
			leaving = new AbortController();
			generation = null;
			thin = null;
			discarded = [];
			working = false;
			if (id !== '') void resume(id, leaving.signal);
		});
	});

	async function resume(id: string, signal: AbortSignal): Promise<void> {
		try {
			const latest = (await getLatestConclusionGeneration(classId, studentId, id)).generation;
			if (signal.aborted || latest === null) return;
			if (latest.status === 'pending' || latest.status === 'running') {
				await follow(latest, signal);
			} else if (latest.status === 'completed') {
				generation = latest;
				await loadWorstCase(signal);
			}
		} catch {
			// Nothing to resume is the normal case; a failed lookup only means
			// the teacher presses the button again.
		}
	}

	async function follow(started: GenerationDto, signal: AbortSignal): Promise<void> {
		working = true;
		try {
			const done = await waitForGeneration(started, signal);
			if (signal.aborted) return;
			if (done.status === 'failed') {
				showToast(done.error ?? 'Mawta no pudo proponer una conclusión esta vez');
				return;
			}
			generation = done;
			await loadWorstCase(signal);
		} finally {
			if (!signal.aborted) working = false;
		}
	}

	async function generate(): Promise<void> {
		if (working || competencyId === '') return;
		thin = null;
		discarded = [];
		const signal = leaving.signal;
		working = true;
		try {
			const started = await generateConclusion(classId, studentId, competencyId);
			await follow(started, signal);
		} catch (error) {
			working = false;
			if (error instanceof GenerationAborted) return;
			if (isAgentUnavailable(error)) {
				agentUnavailable.set(true);
				return;
			}
			if (error instanceof ApiError && error.code === 'insufficient_evidence') {
				thin = (error.body as { evidence?: InsufficientEvidenceDto } | undefined)?.evidence ?? null;
				discarded = list(thin?.discarded_voice_notes);
				if (discarded.length > 0) void loadRoster();
				return;
			}
			showToast(error instanceof ApiError ? error.message : 'No se pudo generar con Mawta');
		}
	}

	// The worst case: every voice note of the student was discarded by the name
	// sweep. Only then does the teacher see them, to move or confirm.
	async function loadWorstCase(signal: AbortSignal): Promise<void> {
		if (!worstCase) return;
		try {
			const res = await getDiscardedVoiceNotes(classId, studentId);
			if (signal.aborted) return;
			discarded = list(res.voice_notes);
			if (discarded.length > 0) await loadRoster();
		} catch {
			showToast('No se pudieron cargar las notas descartadas');
		}
	}

	async function loadRoster(): Promise<void> {
		if (roster.length > 0) return;
		try {
			roster = list((await getClassStudents(classId)).students).filter(
				(s) => s.student_id !== studentId
			);
		} catch {
			// Without the roster only "Sí es de este estudiante" is offered.
		}
	}

	async function confirm(note: DiscardedVoiceNoteDto): Promise<void> {
		if (busyNote) return;
		busyNote = note.id;
		try {
			await confirmVoiceNote(note.id);
			discarded = discarded.filter((n) => n.id !== note.id);
			showToast('Nota recuperada. Vuelve a generar para usarla.');
		} catch (error) {
			showToast(error instanceof ApiError ? error.message : 'No se pudo recuperar la nota');
		} finally {
			busyNote = '';
		}
	}

	async function move(note: DiscardedVoiceNoteDto): Promise<void> {
		const target = moveTo[note.id];
		if (busyNote || !target) return;
		busyNote = note.id;
		try {
			await reassignVoiceNote(note.id, target);
			discarded = discarded.filter((n) => n.id !== note.id);
			const name = roster.find((s) => s.student_id === target)?.full_name ?? 'el otro estudiante';
			showToast(`Nota movida a ${name}`);
		} catch (error) {
			showToast(error instanceof ApiError ? error.message : 'No se pudo mover la nota');
		} finally {
			busyNote = '';
		}
	}

	function use(): void {
		if (proposal && generation) onuse(proposal.body, generation.id);
	}

	// ---- copy ----

	const plural = (n: number, one: string, many: string): string =>
		n === 1 ? one : many.replace('{n}', String(n));

	function warningText(w: ConclusionWarningDto): string {
		const n = w.count ?? 0;
		switch (w.code) {
			case 'voice_notes_discarded':
				return plural(
					n,
					'1 nota de voz no se usó: parece ser de otro estudiante.',
					'{n} notas de voz no se usaron: parecen ser de otros estudiantes.'
				);
			case 'all_voice_notes_discarded':
				return plural(
					n,
					'La única nota de voz de este periodo parece ser de otro estudiante, así que no se usó. Revísala abajo.',
					'Las {n} notas de voz de este periodo parecen ser de otros estudiantes, así que no se usaron. Revísalas abajo.'
				);
			case 'voice_notes_pending':
				return plural(
					n,
					'1 nota de voz aún se está procesando y no se usó.',
					'{n} notas de voz aún se están procesando y no se usaron.'
				);
			case 'no_voice_notes':
				return 'No hay notas de voz este periodo: la propuesta se basa solo en las evidencias y puede ser menos precisa.';
			case 'evidence_single_kind':
				return `Todas las evidencias valoradas son ${w.kind === 'actuacion' ? 'actuaciones' : 'producciones'}. El CNEB pide evidencia variada: revisa que la propuesta no generalice de más.`;
			case 'evidence_single_experience':
				return 'Todas las evidencias valoradas vienen de una sola experiencia. El CNEB recomienda evidencia de diversas situaciones.';
		}
	}

	const sources = (p: ConclusionPointDto): string => {
		const titles = list(p.evidence_ids)
			.map((id) => evidenceTitle(id))
			.filter((t): t is string => !!t);
		const notes = list(p.voice_note_ids).length;
		const parts = [...titles.map((t) => `«${t}»`)];
		if (notes > 0) parts.push(plural(notes, '1 nota de voz', '{n} notas de voz'));
		return parts.join(' · ');
	};

	const REASON_TEXT: Record<DiscardedVoiceNoteDto['discard_reason'], string> = {
		mentions_other_student: 'Nombra a otros estudiantes y no a este.',
		unreadable: 'No se entiende lo que dice.',
	};

	const dateFmt = new Intl.DateTimeFormat('es-PE', { day: 'numeric', month: 'short' });

	const asNote = (n: DiscardedVoiceNoteDto): Note => ({
		id: n.id,
		entryId: '',
		audioBlob: null,
		transcript: n.transcript,
		durationMs: n.duration_ms,
		status: 'saved',
	});
</script>

{#if !$agentUnavailable}
	<div class="assistant">
		{#if level === null}
			<p class="hint">Registra el nivel de logro para que Mawta pueda proponer una conclusión.</p>
		{:else}
			<Button
				variant="secondary"
				type="button"
				icon="sparkles"
				disabled={working}
				onclick={() => void generate()}
			>
				{proposal ? 'Volver a generar con Mawta' : 'Generar con Mawta'}
			</Button>
		{/if}

		{#if working}
			<p class="hint">Mawta está leyendo las evidencias y notas de voz…</p>
		{/if}

		{#if thin}
			<Notice variant="attention">
				<p class="notice-text">
					Hay poca evidencia para proponer una conclusión: {thin.graded_count} de {thin.minimum}
					evidencias valoradas como mínimo. Puedes escribirla a mano.
				</p>
			</Notice>
		{/if}

		{#if proposal}
			<div class="proposal" aria-label="Propuesta de Mawta">
				<p class="eyebrow"><Icon name="sparkles" size={14} /> Propuesta de Mawta</p>
				{#each [{ title: 'Avances', points: list(proposal.progress) }, { title: 'Dificultades', points: list(proposal.difficulties) }, { title: 'Recomendaciones', points: list(proposal.recommendations) }] as section (section.title)}
					{#if section.points.length > 0}
						<p class="section">{section.title}</p>
						{#each section.points as p, i (i)}
							<p class="point">{p.text}</p>
							{#if sources(p)}<p class="source">{sources(p)}</p>{/if}
						{/each}
					{/if}
				{/each}
				{#if proposal.no_progress_justification}
					<p class="section">Por qué no hubo progreso</p>
					<p class="point">{proposal.no_progress_justification}</p>
				{/if}
				{#if proposal.supports_provided}
					<p class="section">Apoyos brindados</p>
					<p class="point">{proposal.supports_provided}</p>
				{/if}
				<div class="use">
					<Button variant="primary" type="button" onclick={use}>Usar esta propuesta</Button>
				</div>
				<p class="hint">
					Se copia al borrador para que la revises y edites. No se guarda hasta que tú lo hagas.
				</p>
			</div>

			{#each warnings as w (w.code)}
				<Notice variant="attention"><p class="notice-text">{warningText(w)}</p></Notice>
			{/each}
		{/if}

		{#if discarded.length > 0}
			<div class="discarded">
				<p class="hint">
					Si alguna es de {studentName}, recupérala. Si es de otro estudiante, muévela: se usará en
					su conclusión.
				</p>
				{#each discarded as n (n.id)}
					<div class="dnote">
						<p class="dmeta">
							{dateFmt.format(new Date(n.recorded_at)).toUpperCase()} · {REASON_TEXT[
								n.discard_reason
							]}
						</p>
						<VoiceNotePlayer note={asNote(n)} />
						<div class="dactions">
							{#if n.discard_reason === 'mentions_other_student'}
								<Button
									variant="secondary"
									type="button"
									disabled={busyNote !== ''}
									onclick={() => void confirm(n)}>Sí es de este estudiante</Button
								>
							{/if}
							{#if roster.length > 0}
								<Field kind="select" label="Mover a" bind:value={moveTo[n.id]}>
									<option value="">Elige un estudiante</option>
									{#each roster as s (s.student_id)}
										<option value={s.student_id}>{s.full_name}</option>
									{/each}
								</Field>
								<Button
									variant="secondary"
									type="button"
									disabled={busyNote !== '' || !moveTo[n.id]}
									onclick={() => void move(n)}>Mover</Button
								>
							{/if}
						</div>
					</div>
				{/each}
			</div>
		{/if}
	</div>
{/if}

<style>
	.assistant {
		display: flex;
		flex-direction: column;
		gap: var(--mw-space-3);
		margin: var(--mw-space-3) 0 var(--mw-space-4);
	}

	.hint {
		margin: 0;
		font-size: var(--mw-type-small-size);
		line-height: 1.4;
		color: var(--mw-ink-muted);
		text-wrap: pretty;
	}

	.notice-text {
		margin: 0;
		font-size: var(--mw-type-small-size);
		line-height: 1.4;
		text-wrap: pretty;
	}

	.proposal {
		padding: var(--mw-space-4);
		border: 1px dashed var(--mw-ink-muted);
		border-radius: var(--mw-radius-md);
	}

	.eyebrow {
		display: flex;
		align-items: center;
		gap: 6px;
		margin: 0 0 var(--mw-space-2);
		font-size: var(--mw-type-label-size);
		font-weight: 600;
		letter-spacing: 0.04em;
		text-transform: uppercase;
		color: var(--mw-ink-muted);
	}

	.section {
		margin: var(--mw-space-3) 0 2px;
		font-size: var(--mw-type-caption-size);
		font-weight: 600;
		color: var(--mw-ink-secondary);
	}

	.point {
		margin: 4px 0 0;
		font-size: var(--mw-type-body-size);
		line-height: 1.45;
		text-wrap: pretty;
	}

	.source {
		margin: 2px 0 0;
		font-size: var(--mw-type-label-size);
		line-height: 1.4;
		color: var(--mw-ink-muted);
	}

	.use {
		margin: var(--mw-space-4) 0 var(--mw-space-2);
	}

	.discarded {
		display: flex;
		flex-direction: column;
		gap: var(--mw-space-3);
	}

	.dnote {
		display: flex;
		flex-direction: column;
		gap: var(--mw-space-2);
	}

	.dmeta {
		margin: 0;
		font-size: var(--mw-type-label-size);
		letter-spacing: 0.04em;
		color: var(--mw-ink-muted);
	}

	.dactions {
		display: flex;
		flex-wrap: wrap;
		align-items: end;
		gap: var(--mw-space-2);
	}
</style>
