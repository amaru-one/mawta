<script lang="ts">
	// Registering a piece of evidencia: a prueba calificada, an examen de
	// recuperación, a tarea — for the whole class, or for one student.
	//
	// This was a 360px dialog. It became a screen for one reason: the decision
	// that makes evidence usable later is which competencia and which criterios
	// it speaks to, and in the dialog that was a 180px scroll box under the fold.
	// Nothing is uploaded here — an evidencia is an evaluation the teacher
	// records, not a file.
	//
	// The criterios are a tag, not a mark. Nothing on this screen computes a
	// nivel de logro, and the copy says so twice because it is what gets
	// misread.
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { ApiError, list } from '$lib/api/client';
	import type {
		AssessmentKind,
		CompetencyCriteriaDto,
		GradingComponentDto,
		ValueScale,
	} from '$lib/api/dto';
	import { createAssessment, getGradingComponents } from '$lib/api/endpoints/classes';
	import { getClassCriteria } from '$lib/api/endpoints/criteria';
	import Icon from '$lib/components/Icon.svelte';
	import TopBar from '$lib/components/TopBar.svelte';
	import { hapticTap } from '$lib/haptics';
	import { usesInternalGrading } from '$lib/stores';
	import { showToast } from '$lib/toast';

	const courseId = $derived(page.params.courseId ?? '');
	// Set, and the evidence belongs to that student alone. The scope is fixed by
	// the caller and stated in a caption rather than offered as a control: which
	// screen you came from is already the answer.
	const scopeStudentId = $derived(page.url.searchParams.get('student'));
	const scopeStudentName = $derived(page.url.searchParams.get('name') ?? 'este alumno');
	const courseName = $derived(page.url.searchParams.get('course') ?? '');

	let ready = $state(false);
	let loadError = $state(false);
	let components = $state<GradingComponentDto[]>([]);
	let comps = $state<CompetencyCriteriaDto[]>([]);

	async function load(): Promise<void> {
		ready = false;
		loadError = false;
		try {
			const [cmp, crits] = await Promise.all([
				getGradingComponents(courseId),
				getClassCriteria(courseId),
			]);
			components = list(cmp.components);
			comps = list(crits.competencies);
			if (competencyId === '' && comps.length > 0) competencyId = comps[0].competency_id;
			ready = true;
		} catch {
			loadError = true;
		}
	}

	onMount(load);

	// ---- the form ----

	const KINDS: { value: AssessmentKind; label: string }[] = [
		{ value: 'quiz', label: 'Quiz' },
		{ value: 'examen', label: 'Examen' },
		{ value: 'practica', label: 'Práctica' },
		{ value: 'tarea', label: 'Tarea' },
		{ value: 'proyecto', label: 'Proyecto' },
		{ value: 'exposicion', label: 'Exposición' },
		{ value: 'participacion', label: 'Participación' },
		{ value: 'rubrica', label: 'Rúbrica' },
		{ value: 'otro', label: 'Otro' },
	];

	let title = $state('');
	let kind = $state<AssessmentKind>('practica');
	// Empty means untouched, which resolves to the first component — reading
	// components[0] into state at init would capture it before the load lands.
	let componentCode = $state('');
	let dueAt = $state('');
	let maxScore = $state('20');
	let competencyId = $state('');
	let picked = $state<Set<string>>(new Set());
	// Class work counts towards the school's average; a per-student piece does
	// not by default — a recovery task that lifted one student's average would
	// hand them an opportunity nobody else got.
	let countsInternal = $state(true);
	let submitting = $state(false);

	// Which scale values this evidence. It is a property of the work, not of the
	// app: the same teacher runs a numeric practice and a lettered exposición in
	// the same week. This is what decides which control appears later on the
	// student's screen.
	let scale = $state<ValueScale>('numeric');

	// A school with no internal system has nothing for a mark to mean, so it
	// falls back to the letter scale rather than a vigesimal one.
	$effect(() => {
		if (!$usesInternalGrading) scale = 'ordinal';
	});

	const effectiveComponent = $derived(componentCode || (components[0]?.code ?? ''));
	const current = $derived(comps.find((c) => c.competency_id === competencyId) ?? null);
	const others = $derived(comps.filter((c) => c.competency_id !== competencyId));

	const canSubmit = $derived(
		title.trim() !== '' &&
			effectiveComponent !== '' &&
			(scale !== 'numeric' || Number(maxScore) > 0)
	);

	function selectCompetency(id: string): void {
		if (id === competencyId) return;
		hapticTap();
		competencyId = id;
		// Criterios belong to a competencia; keeping a tick across a switch would
		// file the evidence against a criterio the teacher can no longer see.
		picked = new Set();
	}

	function toggleCriterion(id: string): void {
		hapticTap();
		const next = new Set(picked);
		if (next.has(id)) next.delete(id);
		else next.add(id);
		picked = next;
	}

	async function submit(e: Event): Promise<void> {
		e.preventDefault();
		if (!canSubmit || submitting) return;
		submitting = true;
		try {
			await createAssessment(courseId, {
				title: title.trim(),
				kind,
				component_code: effectiveComponent,
				value_scale: scale,
				// The denominator belongs to the numeric scale and to nothing else;
				// the server rejects it on the other two rather than storing a number
				// nobody would ever use.
				max_score: scale === 'numeric' ? Number(maxScore) : null,
				// The input is a plain date; the API takes a timestamp.
				due_at: dueAt === '' ? null : `${dueAt}T23:59:00-05:00`,
				student_id: scopeStudentId,
				counts_toward_internal: scale === 'numeric' && countsInternal,
				criterion_ids: [...picked],
			});
			showToast(
				scopeStudentId === null
					? 'Evidencia añadida para toda la clase'
					: `Evidencia añadida para ${scopeStudentName}`
			);
			await goto(`/class/${courseId}`);
		} catch (err) {
			showToast(err instanceof ApiError ? err.message : 'No se pudo añadir la evidencia');
			submitting = false;
		}
	}
</script>

<svelte:head>
	<title>Nueva evidencia — {courseName || 'Clase'}</title>
</svelte:head>

<TopBar back="/class/{courseId}" useHistory />

<div class="body">
	{#if ready}
		<h1 class="title">Nueva evidencia</h1>
		{#if courseName}<span class="sub">{courseName}</span>{/if}
		<p class="lede">
			{#if scopeStudentId === null}
				Registras una evaluación para toda la clase — una prueba calificada, un examen de
				recuperación, una tarea. Queda en la pantalla de cada alumno.
			{:else}
				Solo para {scopeStudentName}. No aparece en la lista de los demás.
			{/if}
		</p>

		<form onsubmit={submit}>
			<p class="eyebrow">La evaluación</p>

			<label class="field">
				<span class="lbl">Título</span>
				<input class="in lead" type="text" bind:value={title} placeholder="Práctica calificada" />
			</label>

			<div class="pair">
				<label class="field">
					<span class="lbl">Tipo</span>
					<select class="in" bind:value={kind}>
						{#each KINDS as k (k.value)}
							<option value={k.value}>{k.label}</option>
						{/each}
					</select>
				</label>
				<label class="field">
					<span class="lbl">Componente</span>
					{#if components.length > 0}
						<select
							class="in"
							value={effectiveComponent}
							onchange={(ev) => (componentCode = ev.currentTarget.value)}
						>
							{#each components as c (c.code)}
								<option value={c.code}>{c.name}</option>
							{/each}
						</select>
					{:else}
						<span class="warn">Esta clase no tiene componentes configurados.</span>
					{/if}
				</label>
			</div>

			<label class="field">
				<span class="lbl">Entrega (opcional)</span>
				<input class="in" type="date" bind:value={dueAt} />
			</label>

			<!-- The scale belongs to the evidence, not to the app: one school runs a
			     vigesimal system, another values in letters only. This is what
			     decides which control appears on the student's screen. -->
			<div class="field">
				<span class="lbl">Cómo se valora</span>
				<div class="scale">
					<button
						type="button"
						class="scell"
						class:on={scale === 'numeric'}
						disabled={!$usesInternalGrading}
						onclick={() => (scale = 'numeric')}
					>
						<span class="scode">0–20</span>
						<span class="sname">Vigesimal</span>
					</button>
					<button
						type="button"
						class="scell"
						class:on={scale === 'ordinal'}
						onclick={() => (scale = 'ordinal')}
					>
						<span class="scode">AD–C</span>
						<span class="sname">Literal</span>
					</button>
				</div>
			</div>

			{#if scale === 'numeric'}
				<label class="field narrow">
					<span class="lbl">Sobre</span>
					<input class="in" type="number" step="0.01" min="0.01" bind:value={maxScore} />
				</label>
			{/if}
			<p class="note">
				{#if scale === 'ordinal'}
					Una letra en un trabajo no es un nivel de logro: ese lo pones tú al cierre, leyendo todo
					el periodo.
				{/if}
			</p>

			<!-- What makes the evidence usable later. -->
			<p class="eyebrow gap">Qué competencia ayuda a valorar</p>
			<p class="note tight">
				Y con qué criterios la vas a leer. El criterio no se califica: es lo que miras en el
				trabajo.
			</p>

			{#if current === null}
				<p class="warn">Esta clase no tiene competencias configuradas.</p>
			{:else}
				<div class="comp">
					<div class="comphead">
						<span class="grow">
							<span class="ccode">{current.code}</span>
							<span class="cname">{current.name}</span>
						</span>
					</div>

					{#if list(current.criteria).length === 0}
						<p class="warn inset">
							Esta competencia todavía no tiene criterios. Escríbelos en «Criterios de evaluación» y
							vuelve.
						</p>
					{:else}
						<div class="crits">
							{#each list(current.criteria) as c (c.criterion_id)}
								<button
									type="button"
									class="crit"
									aria-pressed={picked.has(c.criterion_id)}
									onclick={() => toggleCriterion(c.criterion_id)}
								>
									<span class="box" class:on={picked.has(c.criterion_id)}>
										{#if picked.has(c.criterion_id)}<Icon name="check" size={14} />{/if}
									</span>
									<span class="grow ctext">
										<span class="ccode">{c.code ?? 'CRIT'}</span> · {c.description}
									</span>
								</button>
							{/each}
						</div>
					{/if}
				</div>

				{#if others.length > 0}
					<div class="rest">
						{#each others as c (c.competency_id)}
							<button type="button" class="orow" onclick={() => selectCompetency(c.competency_id)}>
								<span class="ocode">{c.code}</span>
								<span class="grow oname">{c.name}</span>
								<span class="ocount">{list(c.criteria).length}</span>
								<span class="chevron"><Icon name="chevron-right" size={16} /></span>
							</button>
						{/each}
					</div>
				{/if}
			{/if}

			<p class="note">
				Esta evidencia no calcula ni sugiere nada. Al cierre, tú pones el nivel de logro de la
				competencia leyendo todas las del periodo.
			</p>

			{#if scale === 'numeric'}
				<label class="internal">
					<input type="checkbox" bind:checked={countsInternal} />
					<span class="grow">
						Cuenta para el promedio interno del colegio
						<span class="isub">
							Es el sistema vigesimal de la IE, aparte del registro oficial. Marcarla o no, no
							cambia el nivel de logro.
						</span>
					</span>
				</label>
			{/if}

			<button
				type="submit"
				class="btn-block btn-primary pressable submit"
				disabled={!canSubmit || submitting}
			>
				Guardar evidencia
			</button>
			<p class="caption">
				{#if current !== null}{current.code} · {picked.size}
					{picked.size === 1 ? 'criterio' : 'criterios'}{/if}
			</p>
		</form>
	{:else if loadError}
		<p class="warn">
			No se pudo cargar el formulario.
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
	}

	.sub {
		display: block;
		margin: 10px 0 0;
		font-family: var(--font-mono);
		font-size: 11px;
		text-transform: uppercase;
		color: var(--text-muted);
	}

	.lede {
		margin: 10px 0 0;
		font-size: 13px;
		line-height: 1.45;
		color: var(--text-secondary);
		text-wrap: pretty;
	}

	.eyebrow {
		margin: 26px 0 12px;
		font-size: 11px;
		font-weight: 600;
		letter-spacing: 0.08em;
		text-transform: uppercase;
		color: var(--text-muted);
	}

	.eyebrow.gap {
		margin-bottom: 6px;
	}

	.field {
		display: flex;
		flex-direction: column;
		gap: 6px;
		margin-bottom: 14px;
	}

	.field.narrow {
		max-width: 120px;
	}

	.lbl {
		font-family: var(--font-mono);
		font-size: 10px;
		font-weight: 700;
		letter-spacing: 0.08em;
		text-transform: uppercase;
		color: var(--text-muted);
	}

	.in {
		width: 100%;
		height: 48px;
		padding: 0 14px;
		border: 1px solid var(--border);
		border-radius: 12px;
		background: var(--surface-2);
		font-family: inherit;
		font-size: 15px;
		color: var(--text-primary);
	}

	/* The title is what the teacher is really writing; it gets the strong stroke
	   and a size the rest of the form does not. */
	.in.lead {
		border: 1px solid var(--border-strong);
		background: var(--surface-2);
		font-size: 15px;
		padding: 11px 12px;
	}

	.in:focus {
		outline: none;
		border-color: var(--border-strong);
	}

	.pair {
		display: flex;
		gap: 10px;
	}

	.pair .field {
		flex: 1;
		min-width: 0;
	}

	.scale {
		display: flex;
		border: 1px solid var(--border-strong);
		border-radius: var(--radius);
		overflow: hidden;
	}

	.scell {
		flex: 1;
		min-width: 0;
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		gap: 2px;
		height: 54px;
		border-right: 1px solid var(--border-strong);
	}

	.scell:last-child {
		border-right: none;
	}

	.scell.on {
		background: var(--gradient-action);
		color: var(--on-primary);
	}

	.scell:disabled {
		opacity: 0.4;
		cursor: not-allowed;
	}

	.scode {
		font-size: 15px;
		font-weight: 600;
		line-height: 1;
	}

	.sname {
		font-size: 10px;
		line-height: 1.2;
		color: var(--text-muted);
	}

	.scell.on .sname {
		color: rgba(255, 255, 255, 0.7);
	}

	.note {
		margin: 10px 0 0;
		font-size: 12px;
		line-height: 1.45;
		color: var(--text-muted);
		text-wrap: pretty;
	}

	.note.tight {
		margin: 0 0 14px;
	}

	/* The chosen competencia is the only 1px-stroked block of the form: it is the
	   decision that makes the evidence usable later. */
	/* The competencia block is the decision that makes the evidence usable
	   later, so it sits on the tint rather than inside a stroke. */
	.comp {
		background: var(--aurora-tint);
		border-radius: 16px;
		padding: 14px;
	}

	.comphead {
		display: flex;
		align-items: flex-start;
		gap: 12px;
	}

	.ccode {
		font-size: 11px;
		font-weight: 600;
		letter-spacing: 0.04em;
		color: var(--text-muted);
		font-family: var(--font-mono);
	}

	.cname {
		display: block;
		margin-top: 4px;
		font-size: 15px;
		font-weight: 500;
		line-height: 1.3;
		text-wrap: pretty;
	}

	.crits {
		display: flex;
		flex-direction: column;
		margin-top: 12px;
	}

	.crit {
		display: flex;
		align-items: flex-start;
		gap: 10px;
		width: 100%;
		padding: 12px 0;
		border-top: 0.5px solid var(--border);
		text-align: left;
	}

	.box {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 22px;
		height: 22px;
		flex-shrink: 0;
		margin-top: 1px;
		border: 1px solid var(--border-strong);
		border-radius: 5px;
		background: var(--surface-2);
	}

	.box.on {
		border-color: var(--aurora-deep);
		background: var(--aurora-deep);
		color: var(--on-primary);
	}

	.ctext {
		font-size: 13px;
		line-height: 1.35;
		text-wrap: pretty;
	}

	/* The other competencias stay present and one tap away — hairlines, no box. */
	.rest {
		display: flex;
		flex-direction: column;
		margin-top: 8px;
	}

	.orow {
		display: flex;
		align-items: center;
		gap: 10px;
		width: 100%;
		padding: 14px 4px;
		border-bottom: 0.5px solid var(--border);
		text-align: left;
	}

	.ocode {
		flex-shrink: 0;
		font-size: 11px;
		font-weight: 600;
		letter-spacing: 0.04em;
		color: var(--text-muted);
		font-family: var(--font-mono);
	}

	.oname {
		font-size: 13px;
		line-height: 1.3;
		color: var(--text-secondary);
	}

	.ocount {
		flex-shrink: 0;
		font-size: 11px;
		color: var(--text-muted);
		font-family: var(--font-mono);
	}

	.chevron {
		display: flex;
		flex-shrink: 0;
		color: var(--text-muted);
	}

	.internal {
		display: flex;
		align-items: flex-start;
		gap: var(--space-sm);
		margin-top: 22px;
		font-size: 13px;
		line-height: 1.35;
	}

	.internal input {
		flex-shrink: 0;
		margin-top: 2px;
	}

	.isub {
		display: block;
		margin-top: 2px;
		font-size: 11px;
		line-height: 1.35;
		color: var(--text-muted);
	}

	.submit {
		margin-top: 24px;
	}

	.submit:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}

	.caption {
		margin: 10px 0 0;
		font-size: 12px;
		text-align: center;
		color: var(--text-muted);
		font-family: var(--font-mono);
	}

	.warn {
		margin: 0;
		font-size: 13px;
		line-height: 1.45;
		color: var(--text-muted);
	}

	.warn.inset {
		margin-top: 12px;
	}
</style>
