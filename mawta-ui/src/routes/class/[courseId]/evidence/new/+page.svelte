<script lang="ts">
	import {
		Button,
		Checkbox,
		EmptyState,
		Field,
		Icon,
		LoadingState,
		Segmented,
	} from '$lib/design-system';
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
	import type { AssessmentKind, CompetencyCriteriaDto, ValueScale } from '$lib/api/dto';
	import { createAssessment } from '$lib/api/endpoints/classes';
	import { getClassCriteria } from '$lib/api/endpoints/criteria';
	import TopBar from '$lib/components/TopBar.svelte';
	import { hapticTap } from '$lib/haptics';
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
	let comps = $state<CompetencyCriteriaDto[]>([]);

	async function load(): Promise<void> {
		ready = false;
		loadError = false;
		try {
			const crits = await getClassCriteria(courseId);
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
		{ value: 'examen', label: 'Examen' },
		{ value: 'practica', label: 'Práctica' },
		{ value: 'tarea', label: 'Tarea' },
		{ value: 'proyecto', label: 'Proyecto' },
		{ value: 'exposicion', label: 'Exposición' },
		{ value: 'participacion', label: 'Participación' },
		{ value: 'otro', label: 'Otro' },
	];

	let title = $state('');
	let kind = $state<AssessmentKind>('practica');
	let dueAt = $state('');
	let maxScore = $state('20');
	let competencyId = $state('');
	let picked = $state<Set<string>>(new Set());
	let submitting = $state(false);

	// Which scale values this evidence. It is a property of the work, not of the
	// app: the same teacher runs a numeric practice and a lettered exposición in
	// the same week. This is what decides which control appears later on the
	// student's screen.
	let scale = $state<ValueScale>('numeric');

	// The maximum is whatever the teacher says the work is worth — 20, 18, 100 —
	// and the app shows the mark as a percentage of it. Whole numbers only: the
	// ruler on the student's screen has one tick per point.
	const maxValid = $derived(
		Number.isInteger(Number(maxScore)) && Number(maxScore) >= 1 && Number(maxScore) <= 100
	);
	const current = $derived(comps.find((c) => c.competency_id === competencyId) ?? null);
	const others = $derived(comps.filter((c) => c.competency_id !== competencyId));

	// At least one criterio: that is how the evidence reaches a competencia.
	const canSubmit = $derived(
		title.trim() !== '' && picked.size > 0 && (scale !== 'numeric' || maxValid)
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
				value_scale: scale,
				// The denominator belongs to the numeric scale and to nothing else;
				// the server rejects it on the other two rather than storing a number
				// nobody would ever use.
				max_score: scale === 'numeric' ? Number(maxScore) : null,
				// The input is a plain date; the API takes a timestamp.
				due_at: dueAt === '' ? null : `${dueAt}T23:59:00-05:00`,
				student_id: scopeStudentId,
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
<div class="view">
	<TopBar back="/class/{courseId}" />

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

				<Field label="Título" type="text" bind:value={title} placeholder="Práctica calificada" />

				<Field kind="select" label="Tipo" bind:value={kind}>
					{#each KINDS as k (k.value)}
						<option value={k.value}>{k.label}</option>
					{/each}
				</Field>

				<Field label="Entrega (opcional)" type="date" bind:value={dueAt} />

				<!-- The scale belongs to the evidence, not to the app: a numeric practice
			     and a lettered exposición can share a week. This is what decides
			     which control appears on the student's screen. -->
				<div class="field">
					<span class="lbl">Cómo se valora</span>
					<Segmented
						label="Cómo se valora"
						value={scale}
						onchange={(value) => (scale = value as typeof scale)}
						options={[
							{ value: 'numeric', label: 'Numérica · sobre un máximo' },
							{ value: 'ordinal', label: 'Literal · AD–C' },
						]}
					/>
				</div>

				{#if scale === 'numeric'}
					<Field
						label="Nota máxima"
						type="number"
						step="1"
						min="1"
						max="100"
						bind:value={maxScore}
						class="narrow"
					/>
				{/if}
				<p class="note">
					{#if scale === 'numeric'}
						Pones la nota sobre este máximo y la pantalla del alumno la muestra como porcentaje. Una
						nota no es un nivel de logro: ese lo pones tú al cierre, leyendo todo el periodo.
					{:else}
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
					<EmptyState title="Esta clase no tiene competencias configuradas." />
				{:else}
					<div class="comp">
						<div class="comphead">
							<span class="grow">
								<span class="ccode">{current.code}</span>
								<span class="cname">{current.name}</span>
							</span>
						</div>

						{#if list(current.criteria).length === 0}
							<EmptyState
								title="Esta competencia todavía no tiene criterios. Escríbelos en «Criterios de evaluación» y
							vuelve."
							/>
						{:else}
							<div class="crits">
								{#each list(current.criteria) as c (c.criterion_id)}
									<Checkbox
										label={`${c.code ?? 'CRIT'} · ${c.description}`}
										checked={picked.has(c.criterion_id)}
										onchange={() => toggleCriterion(c.criterion_id)}
									/>
								{/each}
							</div>
						{/if}
					</div>

					{#if others.length > 0}
						<div class="rest">
							{#each others as c (c.competency_id)}
								<button
									type="button"
									class="orow"
									onclick={() => selectCompetency(c.competency_id)}
								>
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

				<Button
					variant="primary"
					block
					class="submit"
					type="submit"
					disabled={!canSubmit || submitting}
				>
					Guardar evidencia
				</Button>
				<p class="caption">
					{#if current !== null}{current.code} · {picked.size}
						{picked.size === 1 ? 'criterio' : 'criterios'}{/if}
				</p>
			</form>
		{:else if loadError}
			<p class="warn">
				No se pudo cargar el formulario.
				<Button variant="secondary" onclick={load}>Reintentar</Button>
			</p>
		{:else}<LoadingState label="Cargando…" />{/if}
	</div>
</div>

<style>
	form {
		display: grid;
		gap: var(--mw-space-4);
	}
	.body {
		padding: 20px 20px 32px;
	}

	.title {
		margin: 0;
		padding-bottom: 14px;

		font-size: var(--mw-type-title-size);
		font-weight: 800;
		letter-spacing: -0.03em;
		line-height: var(--mw-type-title-line);
	}

	.sub {
		display: block;
		margin: 10px 0 0;
		font-family: var(--mw-font-sans);
		font-size: var(--mw-type-label-size);
		text-transform: uppercase;
		color: var(--mw-ink-muted);
	}

	.lede {
		margin: 10px 0 0;
		font-size: var(--mw-type-small-size);
		line-height: 1.45;
		color: var(--mw-ink-secondary);
		text-wrap: pretty;
	}

	.eyebrow {
		margin: 26px 0 12px;
		font-size: var(--mw-type-label-size);
		font-weight: 600;
		letter-spacing: 0.04em;
		text-transform: uppercase;
		color: var(--mw-ink-muted);
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
	.view .field:global(.narrow) {
		max-width: 120px;
	}

	.lbl {
		font-family: var(--mw-font-sans);
		font-size: var(--mw-type-label-size);
		font-weight: 700;
		letter-spacing: 0.04em;
		text-transform: uppercase;
		color: var(--mw-ink-muted);
	}
	.view :global(.in) {
		width: 100%;
	}

	.note {
		margin: 10px 0 0;
		font-size: var(--mw-type-caption-size);
		line-height: 1.45;
		color: var(--mw-ink-muted);
		text-wrap: pretty;
	}

	.note.tight {
		margin: 0 0 14px;
	}

	.comp {
		background: var(--mw-surface-tint);
		border-radius: var(--mw-radius-xl);
		padding: 14px;
	}

	.comphead {
		display: flex;
		align-items: flex-start;
		gap: 12px;
	}

	.ccode {
		font-size: var(--mw-type-label-size);
		font-weight: 600;
		letter-spacing: 0.04em;
		color: var(--mw-ink-muted);
		font-family: var(--mw-font-sans);
	}

	.cname {
		display: block;
		margin-top: 4px;
		font-size: var(--mw-type-body-size);
		font-weight: 500;
		line-height: 1.3;
		text-wrap: pretty;
	}

	.crits {
		display: flex;
		flex-direction: column;
		margin-top: 12px;
	}

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
		border-bottom: 1px solid var(--mw-line);
		text-align: left;
	}

	.ocode {
		flex-shrink: 0;
		font-size: var(--mw-type-label-size);
		font-weight: 600;
		letter-spacing: 0.04em;
		color: var(--mw-ink-muted);
		font-family: var(--mw-font-sans);
	}

	.oname {
		font-size: var(--mw-type-small-size);
		line-height: 1.3;
		color: var(--mw-ink-secondary);
	}

	.ocount {
		flex-shrink: 0;
		font-size: var(--mw-type-label-size);
		color: var(--mw-ink-muted);
		font-family: var(--mw-font-sans);
	}

	.chevron {
		display: flex;
		flex-shrink: 0;
		color: var(--mw-ink-muted);
	}
	.view :global(.submit) {
		margin-top: 24px;
	}

	.caption {
		margin: 10px 0 0;
		font-size: var(--mw-type-caption-size);
		text-align: center;
		color: var(--mw-ink-muted);
		font-family: var(--mw-font-sans);
	}

	.warn {
		margin: 0;
		font-size: var(--mw-type-small-size);
		line-height: 1.45;
		color: var(--mw-ink-muted);
	}
</style>
