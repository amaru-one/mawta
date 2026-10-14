<script lang="ts">
	import {
		Action,
		Button,
		Card,
		Checkbox,
		ConfirmDialog,
		EmptyState,
		ErrorNotice,
		Field,
		Icon,
		LoadingState,
	} from '$lib/design-system';
	// One student, one competencia: read, then decide.
	//
	// The order of the screen IS the order of the judgement. The evidence comes
	// first, each piece with its own control permanently open — there is no
	// accordion, because there is no state to remember: nothing expands, nothing
	// collapses, nothing is left half-open. That is only affordable with a
	// control compact enough to sit on every card at once, which is why the mark
	// is a ruler and not a field.
	//
	// Below the evidence, separated by its own heading, sits the one decision
	// that reaches the official record: the nivel de logro. It is the only
	// control on the screen enclosed in a 1px stroke, and that hierarchy is the
	// argument — the marks inform it, none of them computes it (RVM 094-2020,
	// 5.1.1.3 p.2-3).
	import { onMount, untrack } from 'svelte';
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { ApiError, list } from '$lib/api/client';
	import type { CompetencyCriteriaDto, CompetencyLevelDto, EvaluationDto } from '$lib/api/dto';
	import {
		assertCompetencyLevel,
		getStudentCompetencies,
		upsertConclusion,
	} from '$lib/api/endpoints/competencies';
	import { getClassCriteria } from '$lib/api/endpoints/criteria';
	import { correctScore, createScore } from '$lib/api/endpoints/scores';
	import { getStudentEvidence } from '$lib/api/endpoints/students';
	import CompetencyIndex from '$lib/components/CompetencyIndex.svelte';
	import ConclusionAssistant from '$lib/components/ConclusionAssistant.svelte';
	import LevelSelector from '$lib/components/LevelSelector.svelte';
	import ScoreRuler from '$lib/components/ScoreRuler.svelte';
	import TopBar from '$lib/components/TopBar.svelte';
	import { EVIDENCE_KIND_LABEL } from '$lib/evidence';
	import type { Tier } from '$lib/levels';
	import { hapticTap } from '$lib/haptics';
	import { showError, showToast } from '$lib/toast';
	import { guardUnsaved } from '$lib/unsaved.svelte';

	const courseId = $derived(page.params.courseId ?? '');
	const studentId = $derived(page.params.studentId ?? '');
	// No endpoint returns a student's name or the class name, so both travel as
	// query params — the convention the other student screens use. `comp` joins
	// them for the same reason `selected` needs to survive a remount (back
	// navigation, a reload): it names which competencia was being read, and
	// nothing else remembers that once SvelteKit tears the component down.
	const studentName = $derived(page.url.searchParams.get('name') ?? 'Alumno');
	const courseName = $derived(page.url.searchParams.get('course') ?? '');
	const compParam = $derived(page.url.searchParams.get('comp') ?? '');

	let ready = $state(false);
	let loadError = $state(false);
	let evidence = $state<EvaluationDto[]>([]);
	let levels = $state<CompetencyLevelDto[]>([]);
	let comps = $state<CompetencyCriteriaDto[]>([]);
	let selected = $state('');

	let savingScore = $state<Set<string>>(new Set());
	let savingLevel = $state(false);
	let switching = $state(false);

	async function load(): Promise<void> {
		ready = false;
		loadError = false;
		try {
			const [comp, crits] = await Promise.all([
				getStudentCompetencies(courseId, studentId),
				getClassCriteria(courseId),
			]);
			levels = list(comp.competencies);
			comps = list(crits.competencies);
			if (selected === '' && comps.length > 0) {
				selected =
					compParam && comps.some((c) => c.competency_id === compParam)
						? compParam
						: comps[0].competency_id;
			}
			// The server narrows the evidence to the competencia through the
			// criterio tags, so the screen never holds work it is not showing.
			evidence = list(
				(await getStudentEvidence(courseId, studentId, selected || undefined)).evidence
			);
			ready = true;
		} catch {
			loadError = true;
		}
	}

	onMount(load);

	// Changing competencia is a new read: different evidence, different level.
	$effect(() => {
		const competencyId = selected;
		untrack(() => {
			if (!ready || competencyId === '') return;
			switching = true;
			getStudentEvidence(courseId, studentId, competencyId)
				.then((res) => {
					evidence = list(res.evidence);
				})
				.catch(() => {
					showToast('No se pudieron cargar las evidencias de esa competencia');
				})
				.finally(() => {
					switching = false;
				});
		});
	});

	// ---- competencia scope ----

	// Reflects the choice into `?comp=` with replaceState — no new history entry,
	// so a back navigation lands on the URL that already names this competencia
	// instead of on the pre-choice one. The existing `$effect` above (keyed on
	// `selected`) still does the actual refetch; this only makes the choice
	// survive a remount.
	function selectCompetency(id: string): void {
		// Switching would re-seed the draft from the server and lose unsaved text,
		// so ask first. The dialog confirms the switch and discards the draft.
		if (id !== selected && conclusionDirty()) {
			switchTo = id;
			switchOpen = true;
			return;
		}
		applySelection(id);
	}

	function applySelection(id: string): void {
		selected = id;
		const params = new URLSearchParams(page.url.searchParams);
		params.set('comp', id);
		void goto(`?${params.toString()}`, { replaceState: true, keepFocus: true, noScroll: true });
	}

	const indexItems = $derived.by(() => {
		let n = 0;
		return comps.map((c) => {
			const area = c.kind !== 'transversal';
			if (area) n += 1;
			return {
				id: c.competency_id,
				label: area ? String(n) : c.code.replace(/^TRANS-/, ''),
				kind: c.kind,
				// Here it means: this student already has a level in this competencia.
				hasLevel: levels.some((l) => l.competency_id === c.competency_id && l.level !== null),
			};
		});
	});

	const current = $derived(comps.find((c) => c.competency_id === selected) ?? null);
	const currentLevel = $derived(levels.find((l) => l.competency_id === selected) ?? null);

	// ---- evidence values ----

	// The student's valuation of the evidence, if the teacher has made one.
	const markOf = (e: EvaluationDto): number | null => e.score?.raw_value ?? null;
	const letterOf = (e: EvaluationDto): Tier | null => e.score?.level ?? null;
	const percentOf = (e: EvaluationDto): number | null => e.score?.percentage ?? null;
	const notSubmitted = (e: EvaluationDto): boolean => e.score?.status === 'not_submitted';

	// Patch in place rather than refetch: a full reload on every tap would make
	// marking a class feel like waiting on a network.
	function applyScore(
		assessmentId: string,
		scoreId: string,
		status: 'graded' | 'not_submitted',
		rawValue: number | null,
		level: Tier | null
	): void {
		evidence = evidence.map((e) =>
			e.assessment_id === assessmentId
				? {
						...e,
						score: {
							score_id: scoreId,
							status,
							raw_value: rawValue,
							percentage: rawValue !== null && e.max_score ? (rawValue / e.max_score) * 100 : null,
							level,
						},
					}
				: e
		);
	}

	// One writer for both scales. Which of rawValue/level is set is decided by
	// the assessment, never by this screen guessing: the server rejects a letter
	// on a numeric piece and vice versa.
	async function writeScore(
		e: EvaluationDto,
		status: 'graded' | 'not_submitted',
		rawValue: number | null,
		level: Tier | null
	): Promise<void> {
		if (savingScore.has(e.assessment_id)) return;
		savingScore = new Set(savingScore).add(e.assessment_id);
		try {
			const existing = e.score;
			const res =
				existing === null
					? await createScore(e.assessment_id, {
							student_id: studentId,
							status,
							raw_value: rawValue,
							level,
						})
					: await correctScore(existing.score_id, { status, raw_value: rawValue, level });
			applyScore(e.assessment_id, res.id, status, rawValue, level);
		} catch (err) {
			showToast(err instanceof ApiError ? err.message : 'No se pudo guardar — revisa tu conexión');
		} finally {
			const next = new Set(savingScore);
			next.delete(e.assessment_id);
			savingScore = next;
		}
	}

	// Marking "no entregó" clears the value server-side (the live score becomes
	// {status: not_submitted, raw_value: null, level: null}), so by the time the
	// teacher unmarks it there is nothing left in `evidence` to read the old value
	// back from — markOf/letterOf would just return the nulls that are already
	// there. This is the one piece of state this screen keeps outside `evidence`:
	// what the mark was, captured the moment before it is cleared, session-only.
	let lastValue = $state<Map<string, { rawValue: number | null; level: Tier | null }>>(new Map());

	// Marking "no entregó" clears the value; unmarking it restores whichever kind
	// of value the piece carried, from `lastValue` — never from `markOf`/`letterOf`,
	// which by then already read the cleared attempt. With nothing captured (the
	// piece was never graded this session), there is nothing valid to send back —
	// `graded` with no value at all is rejected by the DB's own constraint — so the
	// ruler/letters, left enabled even while marked, are the way out instead.
	function toggleNotSubmitted(e: EvaluationDto): void {
		hapticTap();
		if (notSubmitted(e)) {
			const prev = lastValue.get(e.assessment_id);
			if (prev && (prev.rawValue !== null || prev.level !== null)) {
				void writeScore(e, 'graded', prev.rawValue, prev.level);
			}
		} else {
			lastValue.set(e.assessment_id, { rawValue: markOf(e), level: letterOf(e) });
			void writeScore(e, 'not_submitted', null, null);
		}
	}

	// ---- the decision ----

	async function setLevel(level: Tier): Promise<void> {
		if (savingLevel || selected === '') return;
		savingLevel = true;
		try {
			const previous = currentLevel?.level ?? null;
			await assertCompetencyLevel(courseId, studentId, { competency_id: selected, level });
			showToast('Nivel guardado', previous ? { onUndo: () => void setLevel(previous) } : undefined);
			levels = levels.map((l) =>
				l.competency_id === selected ? { ...l, level, asserted_at: new Date().toISOString() } : l
			);
		} catch (err) {
			showError(err instanceof ApiError ? err.message : 'No se pudo guardar el nivel', {
				onRetry: () => void setLevel(level),
			});
		} finally {
			savingLevel = false;
		}
	}

	// ---- conclusión descriptiva ----
	//
	// Always open, never behind a disclosure: it is one block per competencia,
	// and for a student at level C or with inclusion support it is mandatory —
	// hiding it behind a tap is how it goes unwritten.
	let draft = $state('');
	let withRecs = $state(false);
	let savingConclusion = $state(false);
	// The Mawta proposal the draft started from, sent along when it is saved
	// so the conclusion stays traceable to what the agent read.
	let generationId = $state<string | null>(null);
	let pendingProposal = $state<{ body: string; generationId: string } | null>(null);
	let replaceOpen = $state(false);
	let switchTo = $state<string | null>(null);
	let switchOpen = $state(false);
	let recsError = $state(false);
	// The draft differs from what the server holds for this competencia.
	const conclusionDirty = (): boolean =>
		draft.trim() !== (currentLevel?.conclusion_body ?? '').trim();
	const leave = guardUnsaved(conclusionDirty);

	// Re-seed the draft when the competencia changes, from whatever is on the
	// server. `untrack` so typing does not re-seed it on every keystroke.
	// `includes_recommendations` is not on the DTO, so the box always starts
	// unticked — see this route's SPEC.md.
	$effect(() => {
		const competencyId = selected;
		if (!ready || competencyId === '') return;
		untrack(() => {
			draft = currentLevel?.conclusion_body ?? '';
			withRecs = false;
			generationId = null;
		});
	});

	// Copying a proposal into the draft must not silently throw away text the
	// teacher typed and has not saved.
	function useProposal(body: string, fromGeneration: string): void {
		const saved = (currentLevel?.conclusion_body ?? '').trim();
		if (draft.trim() !== '' && draft.trim() !== saved) {
			pendingProposal = { body, generationId: fromGeneration };
			replaceOpen = true;
			return;
		}
		applyProposal(body, fromGeneration);
	}

	function applyProposal(body: string, fromGeneration: string): void {
		draft = body;
		generationId = fromGeneration;
		// Every Mawta proposal carries at least one recommendation.
		withRecs = true;
		pendingProposal = null;
		showToast('Propuesta copiada al borrador: revísala antes de guardar');
	}

	const evidenceTitle = (assessmentId: string): string | undefined =>
		evidence.find((e) => e.assessment_id === assessmentId)?.title;

	async function saveConclusion(status: 'draft' | 'final'): Promise<void> {
		if (savingConclusion || selected === '' || draft.trim() === '') return;
		// Mirrors the server's 422 missing_recommendations rather than letting the
		// teacher lose the text to a rejection.
		recsError = status === 'final' && !withRecs;
		if (recsError) {
			return;
		}
		savingConclusion = true;
		try {
			await upsertConclusion(courseId, studentId, {
				competency_id: selected,
				body: draft.trim(),
				includes_recommendations: withRecs,
				status,
				generation_id: generationId ?? undefined,
			});
			levels = levels.map((l) =>
				l.competency_id === selected
					? { ...l, conclusion_body: draft.trim(), conclusion_status: status }
					: l
			);
			showToast(status === 'final' ? 'Conclusión guardada como final' : 'Borrador guardado');
		} catch (err) {
			showError(err instanceof ApiError ? err.message : 'No se pudo guardar la conclusión', {
				onRetry: () => void saveConclusion(status),
			});
		} finally {
			savingConclusion = false;
		}
	}

	const REQUIREMENT_TEXT: Record<string, string> = {
		level_c: 'Obligatoria: el nivel de esta competencia es C.',
		level_b: 'Obligatoria: el nivel de esta competencia es B.',
		level_a: 'Obligatoria: el nivel de esta competencia es A.',
		cycle_i_mandatory: 'Obligatoria en todas las competencias de este ciclo.',
		consecutive_c: 'Obligatoria: es el segundo periodo consecutivo en C.',
		inclusion_support: 'Obligatoria: el alumno tiene medidas de inclusión.',
	};

	const dateFmt = new Intl.DateTimeFormat('es-PE', { day: 'numeric', month: 'short' });

	// Kind and date, mono: what the piece was and when it was due. Read as
	// metadata, which is why it is not part of the title line's weight.
	const metaLine = (e: EvaluationDto): string => {
		const kind = (EVIDENCE_KIND_LABEL[e.kind] ?? e.kind).toUpperCase();
		if (e.due_at === null) return kind;
		return `${kind} · ${dateFmt.format(new Date(e.due_at)).toUpperCase()}`;
	};

	// The criterios an evidence declares, as the teacher wrote them: the codes
	// first for scanning, then the text — this is the "what to look at" line, and
	// it is read-only. The criterio is the ruler, never the thing being marked.
	// One criterio reads as a sentence; two or more read as a list, one per line,
	// with the code leading when the criterio has one.
	const critItems = (e: EvaluationDto): string[] =>
		list(e.criteria).map((c) => (c.code ? `${c.code} · ${c.description}` : c.description));
</script>

<svelte:head>
	<title>{studentName} — {courseName || 'Clase'}</title>
</svelte:head>
<div class="view">
	<TopBar back="/class/{courseId}/students" />

	<div class="body">
		{#if ready}
			<h1 class="screen-title">{studentName}</h1>
			{#if courseName}<span class="screen-sub">{courseName}</span>{/if}

			{#if indexItems.length > 0}
				<div class="idx">
					<CompetencyIndex items={indexItems} selectedId={selected} onselect={selectCompetency} />
				</div>
			{/if}

			{#if current !== null}
				<p class="comp">{current.name}</p>

				<!-- READ -->
				<p class="eyebrow">Evidencias del periodo</p>
				<p class="hint">Cada evidencia se valora en su propia escala. Se guarda al tocar.</p>

				{#if evidence.length === 0}
					<EmptyState
						title="Esta competencia no tiene evidencia este periodo."
						description="Se registra desde el área, en «Añadir evidencia», enlazándola a sus criterios."
					/>
				{:else}
					<div class="cards" class:switching>
						{#each evidence as e (e.assessment_id)}
							{@const off = notSubmitted(e)}
							{@const busy = savingScore.has(e.assessment_id)}
							<Card>
								<div class="cardhead">
									<span class="grow etitle">{e.title}</span>
									<span class="emeta">{metaLine(e)}</span>
								</div>
								{#if critItems(e).length === 0}
									<p class="crit">Sin criterios declarados.</p>
								{:else if critItems(e).length === 1}
									<p class="crit">{critItems(e)[0]}</p>
								{:else}
									<ul class="crit-list">
										{#each critItems(e) as item, i (i)}
											<li>{item}</li>
										{/each}
									</ul>
								{/if}

								<!-- The scale is a property of the evidence, so the control is
							     chosen by the work rather than by the screen: a ruler out of
							     the evidence's own maximum, or the AD/A/B/C letters. -->
								{#if e.value_scale === 'numeric' && e.max_score !== null}
									<div class="ruler">
										<ScoreRuler
											value={off ? null : markOf(e)}
											max={e.max_score}
											disabled={busy}
											onselect={(v) => void writeScore(e, 'graded', v, null)}
										/>
									</div>
									{#if !off && percentOf(e) !== null}
										<p class="pct">{Math.round(percentOf(e) ?? 0)} %</p>
									{/if}
								{:else}
									<div class="ruler">
										<LevelSelector
											variant="evidence"
											level={off ? null : letterOf(e)}
											disabled={busy}
											onselect={(l) => void writeScore(e, 'graded', null, l)}
										/>
									</div>
								{/if}

								<Checkbox
									label="No entregó"
									checked={off}
									disabled={busy}
									onchange={() => toggleNotSubmitted(e)}
								/>
							</Card>
						{/each}
					</div>
				{/if}

				<!-- DECIDE -->
				<p class="eyebrow gap">Nivel de logro en esta competencia</p>
				<p class="hint">Lo pones tú, leyendo lo de arriba. Ninguna nota lo calcula.</p>
				<LevelSelector
					level={currentLevel?.level ?? null}
					disabled={savingLevel}
					onselect={(l) => void setLevel(l)}
				/>

				<p class="eyebrow gap">Conclusión descriptiva</p>
				{#if currentLevel?.conclusion_status}<p class="meta">
						Estado: {currentLevel.conclusion_status === 'final' ? 'final' : 'borrador'}
					</p>{/if}
				{#if currentLevel?.conclusion_required}
					<p class="hint req">
						{REQUIREMENT_TEXT[currentLevel.conclusion_requirement] ?? 'Obligatoria.'}
					</p>
				{:else}
					<p class="hint">Opcional en esta competencia.</p>
				{/if}
				<ConclusionAssistant
					classId={courseId}
					{studentId}
					{studentName}
					competencyId={selected}
					level={currentLevel?.level ?? null}
					{evidenceTitle}
					onuse={useProposal}
				/>
				<Field
					kind="textarea"
					label="Conclusión descriptiva"
					rows={4}
					bind:value={draft}
					placeholder="Qué logró, qué le falta y cómo seguir."
				/>
				<Checkbox bind:checked={withRecs}>
					<span class="grow">Incluye recomendaciones personalizadas</span>
				</Checkbox>
				{#if recsError}<p class="mw-field__error" role="alert">
						Para marcarla como final, incluye recomendaciones personalizadas.
					</p>{/if}
				{#if draft.trim() === ''}<p class="meta">
						Escribe la conclusión para poder guardarla.
					</p>{/if}
				<div class="actions">
					<Button
						variant="secondary"
						type="button"
						disabled={savingConclusion || draft.trim() === ''}
						onclick={() => void saveConclusion('draft')}>Guardar borrador</Button
					>
					<Button
						variant="primary"
						type="button"
						disabled={savingConclusion || draft.trim() === ''}
						onclick={() => void saveConclusion('final')}>Marcar como final</Button
					>
				</div>
			{/if}
		{:else if loadError}
			<ErrorNotice message="No se pudo cargar al alumno." onretry={load} />
		{:else}<LoadingState label="Cargando…" />{/if}
	</div>
</div>

<ConfirmDialog
	bind:open={replaceOpen}
	title="¿Reemplazar tu borrador?"
	description="Tienes texto sin guardar. La propuesta de Mawta lo reemplazará."
	confirmLabel="Reemplazar"
	onconfirm={() => {
		if (pendingProposal) applyProposal(pendingProposal.body, pendingProposal.generationId);
	}}
	oncancel={() => (pendingProposal = null)}
/>

<ConfirmDialog
	bind:open={switchOpen}
	title="¿Cambiar de competencia?"
	description="Tienes una conclusión sin guardar en esta competencia."
	confirmLabel="Descartar y cambiar"
	cancelLabel="Seguir aquí"
	onconfirm={() => {
		if (switchTo) applySelection(switchTo);
		switchTo = null;
	}}
	oncancel={() => (switchTo = null)}
/>
<ConfirmDialog
	bind:open={leave.state.open}
	tone="danger"
	title="¿Salir sin guardar?"
	description="Se perderá la conclusión que estás escribiendo."
	confirmLabel="Descartar"
	cancelLabel="Seguir editando"
	onconfirm={leave.confirmLeave}
/>

<style>
	.body {
		padding: 20px 20px 32px;
	}

	.idx {
		margin-top: 14px;
	}

	.comp {
		margin: 16px 0 0;
		font-size: var(--mw-type-body-size);
		font-weight: 600;
		line-height: 1.3;
		letter-spacing: -0.01em;
		text-wrap: pretty;
	}

	.eyebrow.gap {
		margin-top: 34px;
	}

	.hint {
		margin: 0 0 6px;
		font-size: var(--mw-type-small-size);
		line-height: 1.4;
		color: var(--mw-ink-muted);
		text-wrap: pretty;
	}

	.hint.req {
		color: var(--mw-ink);
	}

	.cards {
		display: flex;
		flex-direction: column;
	}

	.cards.switching {
		opacity: 0.5;
	}

	.cardhead {
		display: flex;
		align-items: baseline;
		gap: 12px;
	}

	.etitle {
		font-size: var(--mw-type-heading-size);
		font-weight: 600;
		line-height: 1.25;
	}

	.emeta {
		flex-shrink: 0;
		font-size: var(--mw-type-label-size);
		letter-spacing: 0.04em;
		color: var(--mw-ink-muted);
		font-family: var(--mw-font-sans);
	}

	.crit-list {
		margin: 8px 0 0;
		padding-left: 18px;
		font-size: var(--mw-type-caption-size);
		line-height: 1.4;
		color: var(--mw-ink-secondary);
		text-wrap: pretty;
	}

	.crit-list li + li {
		margin-top: 4px;
	}

	.crit {
		margin: 8px 0 0;
		font-size: var(--mw-type-caption-size);
		line-height: 1.4;
		color: var(--mw-ink-secondary);
		text-wrap: pretty;
	}

	.ruler {
		margin-top: 16px;
	}

	.pct {
		margin: 6px 0 0;
		font-size: var(--mw-type-label-size);
		letter-spacing: 0.04em;
		color: var(--mw-ink-muted);
		font-family: var(--mw-font-sans);
	}

	.actions {
		display: flex;
		gap: var(--mw-space-3);
		margin-top: var(--mw-space-4);
	}
</style>
