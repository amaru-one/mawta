<script lang="ts">
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
	import { page } from '$app/state';
	import { ApiError, list } from '$lib/api/client';
	import type { CompetencyCriteriaDto, CompetencyLevelDto, EvaluationDto } from '$lib/api/dto';
	import {
		assertCompetencyLevel,
		getStudentCompetencies,
		upsertConclusion,
	} from '$lib/api/endpoints/competencies';
	import { getClassCriteria } from '$lib/api/endpoints/criteria';
	import { correctScore, createScore } from '$lib/api/endpoints/grades';
	import { getStudentEvidence } from '$lib/api/endpoints/students';
	import CompetencyIndex from '$lib/components/CompetencyIndex.svelte';
	import Icon from '$lib/components/Icon.svelte';
	import LevelScale from '$lib/components/LevelScale.svelte';
	import LevelSelector from '$lib/components/LevelSelector.svelte';
	import ScoreRuler from '$lib/components/ScoreRuler.svelte';
	import TopBar from '$lib/components/TopBar.svelte';
	import type { Tier } from '$lib/grades';
	import { hapticTap } from '$lib/haptics';
	import { usesInternalGrading } from '$lib/stores';
	import { showToast } from '$lib/toast';

	const courseId = $derived(page.params.courseId ?? '');
	const studentId = $derived(page.params.studentId ?? '');
	// No endpoint returns a student's name or the class name, so both travel as
	// query params — the convention the grades screen already uses.
	const studentName = $derived(page.url.searchParams.get('name') ?? 'Alumno');
	const courseName = $derived(page.url.searchParams.get('course') ?? '');

	let ready = $state(false);
	let loadError = $state(false);
	let evidence = $state<EvaluationDto[]>([]);
	let levels = $state<CompetencyLevelDto[]>([]);
	let comps = $state<CompetencyCriteriaDto[]>([]);
	let selected = $state('');
	/** assessment_id of a score being written — one card never blocks another. */
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
			if (selected === '' && comps.length > 0) selected = comps[0].competency_id;
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

	// The live attempt, if any: the last one the server sent back.
	const liveAttempt = (e: EvaluationDto) => {
		const a = list(e.attempts);
		return a.length === 0 ? null : a[a.length - 1];
	};

	const markOf = (e: EvaluationDto): number | null => liveAttempt(e)?.raw_value ?? null;
	const letterOf = (e: EvaluationDto): Tier | null => liveAttempt(e)?.level ?? null;
	const notSubmitted = (e: EvaluationDto): boolean => liveAttempt(e)?.status === 'not_submitted';

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
						attempts: [
							{ score_id: scoreId, attempt_number: 1, status, raw_value: rawValue, level },
						],
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
			const existing = liveAttempt(e);
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

	// Marking "no entregó" clears the value; unmarking it restores whichever kind
	// of value the piece carries.
	function toggleNotSubmitted(e: EvaluationDto): void {
		hapticTap();
		void (notSubmitted(e)
			? writeScore(e, 'graded', markOf(e), letterOf(e))
			: writeScore(e, 'not_submitted', null, null));
	}

	// ---- the decision ----

	async function setLevel(level: Tier): Promise<void> {
		if (savingLevel || selected === '') return;
		savingLevel = true;
		try {
			await assertCompetencyLevel(courseId, studentId, { competency_id: selected, level });
			levels = levels.map((l) =>
				l.competency_id === selected ? { ...l, level, asserted_at: new Date().toISOString() } : l
			);
		} catch (err) {
			showToast(err instanceof ApiError ? err.message : 'No se pudo guardar el nivel');
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

	// Re-seed the draft when the competencia changes, from whatever is on the
	// server. `untrack` so typing does not re-seed it on every keystroke.
	// `includes_recommendations` is not on the DTO, so the box always starts
	// unticked — see this route's SPEC.md.
	$effect(() => {
		const l = currentLevel;
		untrack(() => {
			draft = l?.conclusion_body ?? '';
			withRecs = false;
		});
	});

	async function saveConclusion(status: 'draft' | 'final'): Promise<void> {
		if (savingConclusion || selected === '' || draft.trim() === '') return;
		// Mirrors the server's 422 missing_recommendations rather than letting the
		// teacher lose the text to a rejection.
		if (status === 'final' && !withRecs) {
			showToast('Una conclusión final debe incluir recomendaciones');
			return;
		}
		savingConclusion = true;
		try {
			await upsertConclusion(courseId, studentId, {
				competency_id: selected,
				body: draft.trim(),
				includes_recommendations: withRecs,
				status,
			});
			levels = levels.map((l) =>
				l.competency_id === selected
					? { ...l, conclusion_body: draft.trim(), conclusion_status: status }
					: l
			);
			showToast(status === 'final' ? 'Conclusión guardada como final' : 'Borrador guardado');
		} catch (err) {
			showToast(err instanceof ApiError ? err.message : 'No se pudo guardar la conclusión');
		} finally {
			savingConclusion = false;
		}
	}

	const REQUIREMENT_TEXT: Record<string, string> = {
		level_c: 'Obligatoria: el nivel de esta competencia es C.',
		consecutive_c: 'Obligatoria: es el segundo periodo consecutivo en C.',
		inclusion_support: 'Obligatoria: el alumno tiene medidas de inclusión.',
	};

	const dateFmt = new Intl.DateTimeFormat('es-PE', { day: 'numeric', month: 'short' });

	// Kind and date, mono: what the piece was and when it was due. Read as
	// metadata, which is why it is not part of the title line's weight.
	const metaLine = (e: EvaluationDto): string => {
		const kind = e.kind.toUpperCase();
		if (e.due_at === null) return kind;
		return `${kind} · ${dateFmt.format(new Date(e.due_at)).toUpperCase()}`;
	};

	// The criterios an evidence declares, as the teacher wrote them: the codes
	// first for scanning, then the text — this is the "what to look at" line, and
	// it is read-only. The criterio is the ruler, never the thing being marked.
	const critLine = (e: EvaluationDto): string => {
		const cs = list(e.criteria);
		if (cs.length === 0) return 'Sin criterios declarados.';
		const codes = cs.map((c) => c.code ?? 'CRIT').join(' ');
		return `${codes} · ${cs.map((c) => c.description).join(' ')}`;
	};
</script>

<svelte:head>
	<title>{studentName} — {courseName || 'Clase'}</title>
</svelte:head>

<TopBar back="/class/{courseId}/students" useHistory />

<div class="body">
	{#if ready}
		<h1 class="title">{studentName}</h1>
		{#if courseName}<span class="sub">{courseName}</span>{/if}

		{#if indexItems.length > 0}
			<div class="idx">
				<CompetencyIndex
					items={indexItems}
					selectedId={selected}
					onselect={(id) => (selected = id)}
				/>
			</div>
		{/if}

		{#if current !== null}
			<p class="comp">{current.name}</p>

			<!-- READ -->
			<p class="eyebrow">Evidencias del periodo</p>
			<p class="hint">Cada evidencia se valora en su propia escala. Se guarda al tocar.</p>

			{#if evidence.length === 0}
				<p class="empty">
					Esta competencia no tiene evidencia este periodo. Se registra desde el área, en «Añadir
					evidencia», enlazándola a sus criterios.
				</p>
			{:else}
				<div class="cards" class:switching>
					{#each evidence as e (e.assessment_id)}
						{@const off = notSubmitted(e)}
						{@const busy = off || savingScore.has(e.assessment_id)}
						<div class="card">
							<div class="cardhead">
								<span class="grow etitle">{e.title}</span>
								<span class="emeta">{metaLine(e)}</span>
							</div>
							<p class="crit">{critLine(e)}</p>

							<!-- The scale is a property of the evidence, so the control is
							     chosen by the work rather than by the screen. `none` shows
							     no control at all: registered, read, never valued. -->
							{#if e.value_scale === 'numeric' && e.max_score !== null && $usesInternalGrading}
								<div class="ruler">
									<ScoreRuler
										value={off ? null : markOf(e)}
										max={e.max_score}
										disabled={busy}
										onselect={(v) => void writeScore(e, 'graded', v, null)}
									/>
								</div>
							{:else if e.value_scale === 'ordinal'}
								<div class="ruler">
									<LevelScale
										level={off ? null : letterOf(e)}
										disabled={busy}
										onselect={(l) => void writeScore(e, 'graded', null, l)}
									/>
								</div>
							{:else}
								<p class="noscale">
									{#if e.value_scale === 'numeric'}
										El colegio no lleva sistema propio de notas, así que esta evidencia no lleva
										valor.
									{:else}
										Sin valor: esta evidencia se registra y se lee, no se puntúa.
									{/if}
								</p>
							{/if}

							<button
								type="button"
								class="mark pressable"
								aria-pressed={off}
								onclick={() => toggleNotSubmitted(e)}
							>
								<span class="grow marklbl" class:on={off}>No entregó</span>
								<span class="box" class:on={off}>
									{#if off}<Icon name="check" size={14} />{/if}
								</span>
							</button>

							{#if !e.counts_toward_internal}
								<p class="tag">Fuera del promedio interno</p>
							{/if}
						</div>
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
			{#if currentLevel?.conclusion_required}
				<p class="hint req">
					{REQUIREMENT_TEXT[currentLevel.conclusion_requirement] ?? 'Obligatoria.'}
				</p>
			{:else}
				<p class="hint">Opcional en esta competencia.</p>
			{/if}
			<textarea
				class="ta"
				rows="4"
				bind:value={draft}
				placeholder="Qué logró, qué le falta y cómo seguir."></textarea>
			<label class="recs">
				<input type="checkbox" bind:checked={withRecs} />
				<span class="grow">Incluye recomendaciones personalizadas</span>
			</label>
			<div class="actions">
				<button
					type="button"
					class="pill-light pressable"
					disabled={savingConclusion || draft.trim() === ''}
					onclick={() => void saveConclusion('draft')}>Guardar borrador</button
				>
				<button
					type="button"
					class="pill-dark pressable"
					disabled={savingConclusion || draft.trim() === ''}
					onclick={() => void saveConclusion('final')}>Marcar como final</button
				>
			</div>
		{/if}
	{:else if loadError}
		<p class="empty">
			No se pudo cargar al alumno.
			<button class="pill-light pressable" onclick={load}>Reintentar</button>
		</p>
	{/if}
</div>

<style>
	.body {
		padding: 22px 18px 40px;
	}

	.title {
		margin: 0;
		padding-bottom: 14px;
		border-bottom: 1.5px solid var(--text-primary);
		font-size: 34px;
		font-weight: 700;
		letter-spacing: -0.02em;
		line-height: 1.1;
		text-wrap: pretty;
	}

	.sub {
		display: block;
		margin: 10px 0 0;
		font-family: var(--font-mono);
		font-size: 11px;
		text-transform: uppercase;
		color: var(--text-muted);
	}

	.idx {
		margin-top: 14px;
	}

	.comp {
		margin: 16px 0 0;
		font-size: 15px;
		font-weight: 600;
		line-height: 1.3;
		letter-spacing: -0.01em;
		text-wrap: pretty;
	}

	.eyebrow {
		margin: 30px 0 4px;
		font-size: 11px;
		font-weight: 600;
		letter-spacing: 0.08em;
		text-transform: uppercase;
		color: var(--text-muted);
	}

	/* The decision needs more air above it than a section break: it is a
	   different kind of act from everything above. */
	.eyebrow.gap {
		margin-top: 34px;
	}

	.hint {
		margin: 0 0 6px;
		font-size: 13px;
		line-height: 1.4;
		color: var(--text-muted);
		text-wrap: pretty;
	}

	.hint.req {
		color: var(--text-primary);
	}

	.cards {
		display: flex;
		flex-direction: column;
	}

	/* Switching competencia is a fresh read; the cards dim rather than vanish. */
	.cards.switching {
		opacity: 0.5;
	}

	/* An evidence with no scale still gets a line, so the gap where a control
	   would be is named rather than left looking broken. */
	.noscale {
		margin: 16px 0 0;
		font-size: 12px;
		line-height: 1.4;
		color: var(--text-muted);
		text-wrap: pretty;
	}

	/* No card chrome: a hairline is enough separation, and a box here would
	   compete with the level selector below, which is the only boxed thing. */
	.card {
		padding: 18px 0;
		border-top: 0.5px solid var(--border);
	}

	.card:last-child {
		border-bottom: 0.5px solid var(--border);
	}

	.cardhead {
		display: flex;
		align-items: baseline;
		gap: 12px;
	}

	.etitle {
		font-size: 16px;
		font-weight: 600;
		line-height: 1.25;
	}

	.emeta {
		flex-shrink: 0;
		font-size: 11px;
		letter-spacing: 0.04em;
		color: var(--text-muted);
		font-family: var(--font-mono);
	}

	.crit {
		margin: 8px 0 0;
		font-size: 12px;
		line-height: 1.4;
		color: var(--text-secondary);
		text-wrap: pretty;
	}

	.ruler {
		margin-top: 16px;
	}

	.mark {
		display: flex;
		align-items: center;
		gap: 12px;
		width: 100%;
		margin-top: 14px;
		text-align: left;
	}

	.marklbl {
		font-size: 14px;
		color: var(--text-secondary);
	}

	.marklbl.on {
		font-weight: 500;
		color: var(--text-primary);
	}

	/* The same marker square the evidence form uses for criterios — one glyph
	   for "I ticked this", everywhere. */
	.box {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 22px;
		height: 22px;
		flex-shrink: 0;
		border: 1px solid var(--border-strong);
		border-radius: 5px;
		background: var(--surface-2);
	}

	.box.on {
		border-color: var(--fill-primary);
		background: var(--fill-primary);
		color: var(--on-primary);
	}

	.tag {
		margin: 10px 0 0;
		font-size: 11px;
		color: var(--text-muted);
		font-family: var(--font-mono);
	}

	.ta {
		width: 100%;
		padding: var(--space-md);
		border: 0.5px solid var(--border);
		border-radius: var(--radius-md);
		background: var(--surface-1);
		font-family: inherit;
		font-size: 14px;
		line-height: 1.45;
		color: var(--text-primary);
		resize: vertical;
	}

	.ta:focus {
		outline: none;
		border-color: var(--border-strong);
	}

	.recs {
		display: flex;
		align-items: flex-start;
		gap: var(--space-sm);
		margin-top: var(--space-md);
		font-size: 13px;
		line-height: 1.35;
	}

	.recs input {
		flex-shrink: 0;
		margin-top: 2px;
	}

	.actions {
		display: flex;
		gap: var(--space-md);
		margin-top: var(--space-lg);
	}

	.actions button:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}

	.empty {
		margin: 12px 0 0;
		font-size: 14px;
		line-height: 1.45;
		color: var(--text-muted);
		text-wrap: pretty;
	}
</style>
